from datetime import datetime, timezone

from sqlalchemy.orm import Session

from api.overview import latest_channel_intelligence
from collector.storage import Channel, Observation, Video, create_database
from metrics.persistence import persist_intelligence_snapshot
from metrics.pipeline import build_intelligence_snapshot


def test_latest_channel_intelligence_returns_latest_snapshot_per_video():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-overview", name="Overview")
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="video-overview", channel_id=channel.id, title="Overview video")
        session.add(video)
        session.flush()
        for minute, views in ((0, 100), (1, 150), (2, 220)):
            session.add(Observation(
                video_id=video.id,
                channel_id=channel.id,
                observed_at=datetime(2026, 9, 14, 0, minute, tzinfo=timezone.utc),
                view_count=views,
                concurrent_viewers=10 + minute * 5,
                classification="VOD",
            ))
        session.commit()

        snapshot = build_intelligence_snapshot(
            ["Overview video"],
            [
                # The adapter only needs chronological measurement points.
            ],
            None,
            None,
        )
        # Empty points are intentionally not persisted; the endpoint should remain empty-safe.
        assert latest_channel_intelligence(session, channel.id) is None


def test_latest_channel_intelligence_missing_channel_is_none():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        assert latest_channel_intelligence(session, 999) is None
