from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.operations import collection_health, intelligence_readiness
from collector.storage import Base, Channel, CollectionRun, Video
from metrics.persistence import IntelligenceSnapshotRecord


def test_collection_health_is_not_fresh_before_run_finished_at():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    finished = datetime(2026, 9, 15, 1, tzinfo=UTC)
    with Session(engine) as session:
        session.add(CollectionRun(started_at=finished - timedelta(minutes=5), finished_at=finished, status="success", channels_attempted=1, videos_observed=1))
        session.commit()
        payload = collection_health(session, as_of=finished - timedelta(minutes=1))
    assert payload["fresh"] is False


def test_intelligence_readiness_ignores_snapshots_after_as_of():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    finished = datetime(2026, 9, 15, 0, tzinfo=UTC)
    as_of = finished + timedelta(minutes=10)
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="channel-1", name="Test")
        session.add(channel)
        session.flush()
        session.add(CollectionRun(started_at=finished - timedelta(minutes=5), finished_at=finished, status="success", channels_attempted=1, videos_observed=1))
        video = Video(youtube_video_id="video-1", channel_id=channel.id, title="Video")
        session.add(video)
        session.flush()
        session.add(IntelligenceSnapshotRecord(video_id=video.id, generated_at=as_of + timedelta(minutes=1), score=90, confidence=0.9, available_signals=4, view_json="{}", contributions_json="[]"))
        session.commit()
        payload = intelligence_readiness(session, as_of=as_of)
    assert payload["ready"] is False
    assert payload["reason"] == "intelligence_coverage_below_threshold"
    assert payload["intelligence"]["videos_with_intelligence"] == 0
    assert payload["intelligence"]["coverage"] == 0.0
