from datetime import datetime, timezone

from sqlalchemy.orm import Session

from collector.intelligence import process_persisted_observations
from collector.storage import Channel, Observation, Video, create_database


def test_process_persisted_observations_builds_snapshot_for_each_video():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-test", name="Test")
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="vid", channel_id=channel.id, title="Story")
        session.add(video)
        session.flush()
        session.add_all([
            Observation(video_id=video.id, channel_id=channel.id,
                        observed_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
                        view_count=100, concurrent_viewers=10, classification="VOD"),
            Observation(video_id=video.id, channel_id=channel.id,
                        observed_at=datetime(2026, 9, 14, 0, 1, tzinfo=timezone.utc),
                        view_count=150, concurrent_viewers=20, classification="VOD"),
        ])
        session.commit()

        result = process_persisted_observations(session)
        assert result.videos_processed == 1
        assert result.snapshots_built == 1
        assert result.errors == 0


def test_process_persisted_observations_is_empty_safe():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        result = process_persisted_observations(session)
        assert result == result.__class__(0, 0, 0)
