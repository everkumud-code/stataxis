from __future__ import annotations

import math

import pytest

from collector.youtube.client import YouTubeAPIError
from collector.youtube.collector import ChannelTarget, collect_channels_batched


class CountingClient:
    """Fake YouTube client that counts calls (each call is 1 quota unit)."""

    def __init__(self, videos_per_channel: int = 25, missing: set[str] | None = None) -> None:
        self.videos_per_channel = videos_per_channel
        self.missing = missing or set()
        self.channel_calls: list[int] = []
        self.upload_calls = 0
        self.video_calls: list[int] = []

    def get_channels(self, channel_ids: list[str]):
        assert len(channel_ids) <= 50
        self.channel_calls.append(len(channel_ids))
        return [
            {
                "id": channel_id,
                "snippet": {"customUrl": f"@{channel_id}", "thumbnails": {"default": {"url": f"https://img/{channel_id}.png"}}},
                "statistics": {"subscriberCount": "1000", "viewCount": "5000", "videoCount": "10"},
                "contentDetails": {"relatedPlaylists": {"uploads": f"uploads-{channel_id}"}},
            }
            for channel_id in channel_ids
            if channel_id not in self.missing
        ]

    def list_uploads(self, uploads_id: str, max_results: int = 25):
        self.upload_calls += 1
        channel_id = uploads_id.removeprefix("uploads-")
        count = min(max_results, self.videos_per_channel)
        return {"items": [{"contentDetails": {"videoId": f"{channel_id}-v{i}"}} for i in range(count)]}

    def get_videos(self, video_ids: list[str]):
        assert len(video_ids) <= 50
        self.video_calls.append(len(video_ids))
        return [
            {
                "id": video_id,
                "snippet": {"title": f"Title {video_id}", "publishedAt": "2026-09-14T00:00:00Z"},
                "statistics": {"viewCount": "250"},
            }
            for video_id in video_ids
        ]


def _targets(count: int) -> list[ChannelTarget]:
    return [ChannelTarget(f"UC{i}", f"Channel {i}") for i in range(count)]


def test_batched_collection_uses_far_fewer_units_for_200_channels() -> None:
    client = CountingClient(videos_per_channel=25)
    result = collect_channels_batched(client, _targets(200), max_videos=25)

    units = len(client.channel_calls) + client.upload_calls + len(client.video_calls)
    assert len(client.channel_calls) == math.ceil(200 / 50) == 4
    assert client.upload_calls == 200
    assert len(client.video_calls) == math.ceil(200 * 25 / 50) == 100
    assert units == 304  # the one-at-a-time approach needs 600
    assert len(result) == 200


def test_each_channel_keeps_its_own_videos_stats_and_metadata() -> None:
    result = collect_channels_batched(CountingClient(videos_per_channel=3), _targets(2), max_videos=3)

    first = result["UC0"]
    assert [o.video_id for o in first.observations] == ["UC0-v0", "UC0-v1", "UC0-v2"]
    assert all(o.channel_id == "UC0" for o in first.observations)
    assert first.subscribers == 1000 and first.total_views == 5000 and first.video_count == 10
    assert first.avatar_url == "https://img/UC0.png"
    assert first.handle == "@UC0"
    assert [o.video_id for o in result["UC1"].observations] == ["UC1-v0", "UC1-v1", "UC1-v2"]


def test_max_videos_is_respected() -> None:
    client = CountingClient(videos_per_channel=25)
    result = collect_channels_batched(client, _targets(1), max_videos=5)
    assert len(result["UC0"].observations) == 5


def test_duplicate_targets_are_fetched_once() -> None:
    client = CountingClient(videos_per_channel=1)
    targets = _targets(1) + _targets(1)
    result = collect_channels_batched(client, targets, max_videos=1)
    assert client.upload_calls == 1
    assert list(result) == ["UC0"]


def test_missing_channel_is_skipped_and_reported_without_stopping_the_others() -> None:
    skipped: dict[str, str] = {}
    result = collect_channels_batched(CountingClient(missing={"UC1"}), _targets(3), max_videos=1, skipped=skipped)
    assert sorted(result) == ["UC0", "UC2"]
    assert skipped == {"UC1": "channel not found"}


def test_uploads_playlist_404_skips_only_that_channel() -> None:
    class Client(CountingClient):
        def list_uploads(self, uploads_id: str, max_results: int = 25):
            if uploads_id == "uploads-UC1":
                raise YouTubeAPIError("not found", status_code=404)
            return super().list_uploads(uploads_id, max_results)

    skipped: dict[str, str] = {}
    result = collect_channels_batched(Client(), _targets(3), max_videos=1, skipped=skipped)
    assert sorted(result) == ["UC0", "UC2"]
    assert skipped == {"UC1": "uploads playlist not found"}


@pytest.mark.parametrize("status", [403, 429])
def test_quota_errors_still_abort_the_pass(status: int) -> None:
    class Client(CountingClient):
        def list_uploads(self, uploads_id: str, max_results: int = 25):
            raise YouTubeAPIError("boom", status_code=status)

    with pytest.raises(YouTubeAPIError):
        collect_channels_batched(Client(), _targets(2), max_videos=1)


def test_no_targets_makes_no_calls() -> None:
    client = CountingClient()
    assert collect_channels_batched(client, [], max_videos=5) == {}
    assert (client.channel_calls, client.upload_calls, client.video_calls) == ([], 0, [])


@pytest.mark.parametrize("error", [YouTubeAPIError("server error", status_code=500), ValueError("bad payload")])
def test_other_per_channel_failures_are_skipped(error: Exception) -> None:
    class Client(CountingClient):
        def list_uploads(self, uploads_id: str, max_results: int = 25):
            if uploads_id == "uploads-UC1":
                raise error
            return super().list_uploads(uploads_id, max_results)

    skipped: dict[str, str] = {}
    result = collect_channels_batched(Client(), _targets(3), max_videos=1, skipped=skipped)
    assert sorted(result) == ["UC0", "UC2"]
    assert list(skipped) == ["UC1"] and skipped["UC1"].startswith("uploads request failed")


def test_local_request_budget_exhaustion_aborts_the_pass() -> None:
    from collector.youtube.quota import QuotaGuardError

    class Client(CountingClient):
        def list_uploads(self, uploads_id: str, max_results: int = 25):
            raise QuotaGuardError("collector daily request budget reached")

    with pytest.raises(QuotaGuardError):
        collect_channels_batched(Client(), _targets(2), max_videos=1)
