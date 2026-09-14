from datetime import datetime, timezone
import json

from sqlalchemy.orm import Session

from collector.intelligence import process_persisted_observations
from collector.storage import Channel, Observation, Video, create_database
from metrics.persistence import IntelligenceSnapshotRecord


def test_collection_pass_persists_traceable_intelligence():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-test", name="Test")
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="vid", channel_id=channel.id, title="Story")
        session.add(video)
        session.flush()
        for minute, views, concurrent in ((0, 100, 10), (1, 160, 20), (2, 250, 35)):
            session.add(Observation(
                video_id=video.id,
                channel_id=channel.id,
                observed_at=datetime(2026, 9, 14, 0, minute, tzinfo=timezone.utc),
                view_count=views,
                concurrent_viewers=concurrent,
                classification="VOD",
            ))
        session.commit()

        result = process_persisted_observations(session)
        record = session.query(IntelligenceSnapshotRecord).one()
        view = json.loads(record.view_json)
        contributions = json.loads(record.contributions_json)

        assert result.snapshots_built == 1
        assert record.score is not None
        assert record.available_signals >= 3
        assert contributions and "weighted_contribution" not in contributions[0]
        assert "contribution" in contributions[0]
        assert "share_of_score" in contributions[0]
        assert view["data"]
        assert view["analysis"]
        assert isinstance(view["view"], str)
        assert view["signals"]
        assert view["measurement_provenance"]["observation_count"] == 3


def test_missing_time_series_does_not_create_fake_score():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-test", name="Test")
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="vid", channel_id=channel.id, title="Story")
        session.add(video)
        session.flush()
        session.add(Observation(
            video_id=video.id,
            channel_id=channel.id,
            observed_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
            view_count=100,
            concurrent_viewers=None,
            classification="VOD",
        ))
        session.commit()

        result = process_persisted_observations(session)
        assert result.snapshots_built == 0
        assert session.query(IntelligenceSnapshotRecord).count() == 0
