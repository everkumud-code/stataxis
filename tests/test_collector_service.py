from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from threading import Event

from sqlalchemy.orm import Session

from collector import service
from collector.storage import Channel, Observation, Video, create_database
from collector.youtube.client import YouTubeAPIError


class FakeLiveClient:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def get_live_videos(self, video_ids):
        self.calls.append(list(video_ids))
        return self.responses.get(tuple(video_ids), [
            {
                "id": video_id,
                "liveStreamingDetails": {"actualStartTime": "2026-09-16T09:00:00Z"},
                "statistics": {"viewCount": "100"},
            }
            for video_id in video_ids
        ])


def _candidate(video_id: str):
    channel = SimpleNamespace(
        youtube_channel_id="UC-" + video_id,
        name="Channel",
        network="Network",
        language="Hindi",
        region="North",
        active=True,
    )
    video = SimpleNamespace(
        youtube_video_id=video_id,
        title="Title",
        published_at=None,
    )
    observation = SimpleNamespace(is_live=True)
    return observation, video, channel


def test_poll_live_once_batches_video_ids_in_groups_of_50(monkeypatch):
    candidates = [_candidate(f"video-{index}") for index in range(101)]
    monkeypatch.setattr(service, "_live_candidates", lambda session, now: candidates)
    monkeypatch.setattr(service, "save_observations", lambda **kwargs: 1)
    client = FakeLiveClient()

    result = service.poll_live_once(object(), client, now=datetime.now(UTC))

    assert [len(call) for call in client.calls] == [50, 50, 1]
    assert result.candidates == 101
    assert result.batches == 3
    assert result.observations_saved == 101


def test_poll_live_once_stops_after_final_non_live_observation():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-stop", name="Stop", network="N", language="Hindi", region="North")
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="video-stop", channel_id=channel.id, title="Live")
        session.add(video)
        session.flush()
        started = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
        session.add(Observation(
            video_id=video.id,
            channel_id=channel.id,
            observed_at=started,
            concurrent_viewers=100,
            is_live=True,
        ))
        session.commit()

        ended_at = started + timedelta(minutes=1)
        client = FakeLiveClient()
        client.responses[("video-stop",)] = [{
            "id": "video-stop",
            "liveStreamingDetails": {
                "actualStartTime": started.isoformat().replace("+00:00", "Z"),
                "actualEndTime": ended_at.isoformat().replace("+00:00", "Z"),
            },
            "statistics": {"viewCount": "150"},
        }]

        result = service.poll_live_once(session, client, now=ended_at)
        assert result.ended == 1
        assert result.observations_saved == 1

        latest = session.query(Observation).order_by(Observation.observed_at.desc()).first()
        assert latest is not None
        assert latest.is_live is False
        assert service._live_candidates(session, ended_at) == []


def test_live_poll_interval_rejects_values_below_30(monkeypatch):
    monkeypatch.setenv("LIVE_POLL_SECONDS", "29")
    try:
        service.interval_seconds("LIVE_POLL_SECONDS", 30, 30)
    except ValueError as exc:
        assert str(exc) == "LIVE_POLL_SECONDS must be at least 30 seconds"
    else:
        raise AssertionError("sub-30-second live polling interval was accepted")


def test_quota_backoff_grows_and_caps():
    assert service.quota_backoff_seconds(1) == 30
    assert service.quota_backoff_seconds(2) == 60
    assert service.quota_backoff_seconds(3) == 120
    assert service.quota_backoff_seconds(10) == 300


def test_service_installs_sigterm_handler(monkeypatch):
    stop_event = Event()
    handlers = {}

    def fake_signal(signum, handler):
        handlers[signum] = handler

    monkeypatch.setattr(service.signal, "signal", fake_signal)
    service.install_signal_handlers(stop_event)

    handlers[service.signal.SIGTERM]()
    assert stop_event.is_set()


def test_poll_live_once_propagates_quota_errors_for_service_backoff(monkeypatch):
    candidates = [_candidate("video-quota")]
    monkeypatch.setattr(service, "_live_candidates", lambda session, now: candidates)

    class QuotaClient:
        def get_live_videos(self, video_ids):
            raise YouTubeAPIError("quota", status_code=429)

    try:
        service.poll_live_once(object(), QuotaClient(), now=datetime.now(UTC))
    except YouTubeAPIError as exc:
        assert exc.status_code == 429
    else:
        raise AssertionError("quota error was swallowed")
