from datetime import UTC, datetime

from collector.storage import Observation, create_database
from collector.youtube.collector import VideoObservation
from collector.youtube.live_watcher import run_manual_live_watch
from collector.youtube.manual_live import ManualLiveTarget
from sqlalchemy.orm import Session


class FakeClient:
    def __init__(self, observations: list[VideoObservation]) -> None:
        self.observations = observations
        self.calls = 0

    def get_videos(self, video_ids: list[str]) -> list[dict]:
        item = self.observations[min(self.calls, len(self.observations) - 1)]
        self.calls += 1
        return [
            {
                "id": item.video_id,
                "snippet": {
                    "channelId": "channel-123",
                    "title": "Original YouTube title",
                    "publishedAt": item.published_at,
                },
                "statistics": {
                    "viewCount": str(item.view_count or 0),
                    "likeCount": str(item.like_count or 0),
                    "commentCount": str(item.comment_count or 0),
                },
                "liveStreamingDetails": {
                    "actualStartTime": item.live_started_at,
                    **({"actualEndTime": item.live_ended_at} if item.live_ended_at else {}),
                    **(
                        {"concurrentViewers": str(item.concurrent_viewers)}
                        if item.concurrent_viewers is not None
                        else {}
                    ),
                },
            }
        ]


def _database() -> Session:
    engine = create_database("sqlite:///:memory:")
    return Session(engine)


def _observation(is_live: bool, concurrent: int) -> VideoObservation:
    return VideoObservation(
        video_id="video-1",
        channel_id="channel-123",
        observed_at=datetime.now(UTC),
        title="Manual Live",
        published_at="2026-09-14T12:00:00Z",
        view_count=1000,
        like_count=50,
        comment_count=10,
        concurrent_viewers=concurrent,
        is_live=is_live,
        classification="LIVE" if is_live else "VOD",
        live_started_at="2026-09-14T12:00:00Z",
        live_ended_at=None if is_live else "2026-09-14T12:30:00Z",
    )


def test_live_watcher_persists_each_poll_and_stops_after_end() -> None:
    target = ManualLiveTarget.from_url("https://www.youtube.com/watch?v=video-1", "Election Live")
    client = FakeClient([_observation(True, 1200), _observation(True, 1450), _observation(False, 0)])
    session = _database()

    saved = run_manual_live_watch(
        client,
        session,
        target,
        interval_seconds=30,
        sleep=lambda _: None,
    )

    assert saved == 3
    rows = session.query(Observation).all()
    assert len(rows) == 3
    assert [row.concurrent_viewers for row in rows] == [1200, 1450, 0]
    assert rows[-1].is_live is False


def test_live_watcher_validates_interval() -> None:
    target = ManualLiveTarget.from_url("https://www.youtube.com/watch?v=video-1", "Election Live")
    session = _database()

    try:
        run_manual_live_watch(FakeClient([_observation(True, 100)]), session, target, interval_seconds=10)
    except ValueError as exc:
        assert "30 seconds" in str(exc)
    else:
        raise AssertionError("expected interval validation")
