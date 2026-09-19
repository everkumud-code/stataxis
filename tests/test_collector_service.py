from datetime import UTC, datetime, timedelta
import threading

from sqlalchemy.orm import Session

from collector import service
from collector.storage import Channel, Observation, Video, create_database


class FakeLiveClient:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or []

    def get_live_videos(self, ids):
        self.calls.append(ids)
        if self.responses:
            return self.responses.pop(0)
        return []


def _seed_live(engine, count=1):
    with Session(engine) as session:
        channel = Channel(
            youtube_channel_id="UC-service",
            name="Service",
            network="Test",
            language="hi-IN",
            region="India",
            active=True,
        )
        session.add(channel)
        session.flush()
        for index in range(count):
            video = Video(
                youtube_video_id=f"video-{index}",
                channel_id=channel.id,
                title=f"Video {index}",
            )
            session.add(video)
            session.flush()
            session.add(
                Observation(
                    video_id=video.id,
                    channel_id=channel.id,
                    observed_at=datetime.now(UTC),
                    concurrent_viewers=100,
                    is_live=True,
                )
            )
        session.commit()


def test_live_poller_batches_video_ids_by_50():
    engine = create_database("sqlite:///:memory:")
    _seed_live(engine, 101)
    client = FakeLiveClient()
    with Session(engine) as session:
        fetched, saved = service.poll_live_once(session, client)
    assert [len(batch) for batch in client.calls] == [50, 50, 1]
    assert fetched == 0
    assert saved == 0


def test_live_poller_stops_after_final_non_live_observation():
    engine = create_database("sqlite:///:memory:")
    _seed_live(engine, 1)
    now = datetime.now(UTC)
    client = FakeLiveClient([
        [{
            "id": "video-0",
            "snippet": {"channelId": "UC-service", "title": "Video 0", "liveBroadcastContent": "none"},
            "statistics": {"viewCount": "200"},
            "liveStreamingDetails": {"actualStartTime": "2026-09-19T10:00:00Z", "actualEndTime": "2026-09-19T11:00:00Z"},
        }]
    ])
    with Session(engine) as session:
        fetched, saved = service.poll_live_once(session, client, now=now)
        assert (fetched, saved) == (1, 1)
        assert service._live_video_ids(session, now=now + timedelta(seconds=1)) == []


def test_live_poller_enforces_minimum_interval():
    import pytest

    with pytest.raises(ValueError):
        service._bounded_interval("LIVE_POLL_SECONDS", 30, 30)


def test_quota_backoff_grows_and_is_capped():
    assert service.quota_backoff_seconds(1) == 30
    assert service.quota_backoff_seconds(2) == 60
    assert service.quota_backoff_seconds(10) == 300


def test_sigterm_handler_sets_stop_event(monkeypatch):
    handlers = {}
    monkeypatch.setattr(service.signal, "signal", lambda signum, handler: handlers.setdefault(signum, handler))
    stop_event = threading.Event()
    service.install_signal_handlers(stop_event)
    handlers[service.signal.SIGTERM]()
    assert stop_event.is_set()
