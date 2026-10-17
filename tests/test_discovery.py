"""New live streams of the tracked channels are found between two collection passes and tracked at once. A fake YouTube client and a scratch database; nothing here calls YouTube."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from collector.discovery import discover_new_streams, streaming_channels, uploads_playlist_id
from collector.storage import Base, Channel, Observation, Video
from collector.youtube.client import YouTubeAPIError

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def cid(n: int) -> str:
    return "UC" + f"{n:022d}"


def make_session():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return Session(engine)


def channel(s, n, name, active=True, streamed_days_ago=None):
    c = Channel(youtube_channel_id=cid(n), name=name, network="n", language="Hindi", region="India", segment="news", active=active)
    s.add(c)
    s.flush()
    if streamed_days_ago is not None:
        s.add(Video(youtube_video_id=f"old{n}", channel_id=c.id, title="old stream", live_started_at=NOW - timedelta(days=streamed_days_ago)))
    s.commit()
    return c


def video(vid, kind):
    base = {"id": vid, "snippet": {"title": f"title {vid}", "publishedAt": "2026-10-17T11:00:00Z", "liveBroadcastContent": "none"}, "statistics": {"viewCount": "10"}, "contentDetails": {"duration": "PT20M"}}
    if kind == "live":
        base["snippet"]["liveBroadcastContent"] = "live"
        base["liveStreamingDetails"] = {"actualStartTime": "2026-10-17T11:30:00Z", "concurrentViewers": "1200"}
    elif kind == "upcoming":
        base["snippet"]["liveBroadcastContent"] = "upcoming"
        base["liveStreamingDetails"] = {"scheduledStartTime": "2026-10-17T15:00:00Z"}
    elif kind == "ended":
        base["liveStreamingDetails"] = {"actualStartTime": "2026-10-17T08:00:00Z", "actualEndTime": "2026-10-17T09:00:00Z"}
    return base


class FakeClient:
    def __init__(self, playlists, videos, fail=None):
        self.playlists, self.videos, self.fail = playlists, videos, fail or {}
        self.playlist_calls, self.video_calls = [], []

    def list_uploads(self, playlist_id, max_results=25):
        self.playlist_calls.append((playlist_id, max_results))
        if playlist_id in self.fail:
            raise YouTubeAPIError("boom", status_code=self.fail[playlist_id])
        return {"items": [{"contentDetails": {"videoId": v}} for v in self.playlists.get(playlist_id, [])]}

    def get_videos(self, ids):
        self.video_calls.append(list(ids))
        return [self.videos[i] for i in ids if i in self.videos]


def test_the_uploads_playlist_is_the_channel_id_with_uu():
    assert uploads_playlist_id(cid(5)) == "UU" + f"{5:022d}"
    assert uploads_playlist_id("UCshort") is None and uploads_playlist_id("XX" + "1" * 22) is None


def test_only_active_channels_that_streamed_lately_are_scanned():
    s = make_session()
    a = channel(s, 1, "Streams often", streamed_days_ago=2)
    channel(s, 2, "Streamed long ago", streamed_days_ago=40)
    channel(s, 3, "Never streamed")
    channel(s, 4, "Switched off", active=False, streamed_days_ago=1)
    assert [c.id for c in streaming_channels(s, NOW)] == [a.id]


def test_a_new_live_stream_is_stored_at_once_and_everything_else_is_left_alone():
    s = make_session()
    a = channel(s, 1, "Alpha", streamed_days_ago=1)
    client = FakeClient({"UU" + f"{1:022d}": ["old1", "NEWLIVE", "NEWUP", "NEWVID", "NEWENDED"]},
                        {"NEWLIVE": video("NEWLIVE", "live"), "NEWUP": video("NEWUP", "upcoming"), "NEWVID": video("NEWVID", "plain"), "NEWENDED": video("NEWENDED", "ended")})
    out = discover_new_streams(s, client, now=NOW)
    assert (out.channels, out.unknown, out.added, out.errors) == (1, 4, 1, 0)       # "old1" is known and is not asked about again
    assert client.video_calls == [["NEWLIVE", "NEWUP", "NEWVID", "NEWENDED"]]
    stored = s.query(Video).filter_by(youtube_video_id="NEWLIVE").one()
    assert stored.channel_id == a.id and stored.live_started_at is not None
    ob = s.query(Observation).filter_by(video_id=stored.id).one()
    assert ob.is_live is True and ob.concurrent_viewers == 1200 and ob.classification == "LIVE"
    for left in ("NEWUP", "NEWVID", "NEWENDED"):
        assert s.query(Video).filter_by(youtube_video_id=left).count() == 0         # left for the normal pass, never marked as known before it is collected properly
    again = discover_new_streams(s, client, now=NOW)
    assert again.added == 0 and s.query(Video).filter_by(youtube_video_id="NEWLIVE").count() == 1     # a second scan does not store it twice


def test_the_stream_is_tracked_by_the_live_poll_from_then_on():
    from collector.service import _live_candidates
    s = make_session()
    channel(s, 1, "Alpha", streamed_days_ago=1)
    discover_new_streams(s, FakeClient({"UU" + f"{1:022d}": ["NEWLIVE"]}, {"NEWLIVE": video("NEWLIVE", "live")}), now=NOW)
    assert [v.youtube_video_id for _o, v, _c in _live_candidates(s, datetime.now(UTC))] == ["NEWLIVE"]


def test_one_bad_channel_is_skipped_but_a_quota_error_stops_the_scan():
    s = make_session()
    channel(s, 1, "Alpha", streamed_days_ago=1)
    channel(s, 2, "Beta", streamed_days_ago=1)
    ok = {"UU" + f"{2:022d}": ["B1"]}
    out = discover_new_streams(s, FakeClient(ok, {"B1": video("B1", "live")}, fail={"UU" + f"{1:022d}": 404}), now=NOW)
    assert out.errors == 1 and out.added == 1
    with pytest.raises(YouTubeAPIError):
        discover_new_streams(s, FakeClient(ok, {}, fail={"UU" + f"{1:022d}": 403}), now=NOW)


def test_a_new_stream_of_a_channel_is_secondary_not_primary():
    """A stream found this way is live for minutes, so by the Primary rule (the long-running main stream) it is Secondary."""
    from metrics.feeds import min_primary_hours
    assert min_primary_hours() >= 24 * 7      # a primary stream has been live for days, so nothing discovered here can be one
