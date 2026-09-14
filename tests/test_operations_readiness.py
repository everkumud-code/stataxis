from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.operations import intelligence_readiness
from collector.storage import Base, Channel, CollectionRun, Video
from metrics.persistence import IntelligenceSnapshotRecord


def test_readiness_with_complete_intelligence():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    finished = datetime(2026, 9, 15, 0, tzinfo=UTC)
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="channel-1", name="Test")
        session.add(channel)
        session.flush()
        session.add(CollectionRun(started_at=finished - timedelta(minutes=5), finished_at=finished, status="success", channels_attempted=1, videos_observed=2))
        for index in range(2):
            video = Video(youtube_video_id=f"video-{index}", channel_id=channel.id, title=f"Video {index}")
            session.add(video)
            session.flush()
            session.add(IntelligenceSnapshotRecord(video_id=video.id, generated_at=finished + timedelta(minutes=1), score=80 + index, confidence=0.8, available_signals=4, view_json="{}", contributions_json="[]"))
        session.commit()
        payload = intelligence_readiness(session, as_of=finished + timedelta(minutes=30))
    assert payload["ready"] is True
    assert payload["reason"] == "ready"
    assert payload["intelligence"]["videos_with_intelligence"] == 2
    assert payload["intelligence"]["coverage"] == 1.0


def test_readiness_reports_partial_coverage():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    finished = datetime(2026, 9, 15, 0, tzinfo=UTC)
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="channel-1", name="Test")
        session.add(channel)
        session.flush()
        session.add(CollectionRun(started_at=finished - timedelta(minutes=5), finished_at=finished, status="success", channels_attempted=1, videos_observed=4))
        video = Video(youtube_video_id="video-1", channel_id=channel.id, title="Video")
        session.add(video)
        session.flush()
        session.add(IntelligenceSnapshotRecord(video_id=video.id, generated_at=finished + timedelta(minutes=1), score=75, confidence=0.7, available_signals=3, view_json="{}", contributions_json="[]"))
        session.commit()
        payload = intelligence_readiness(session, as_of=finished + timedelta(minutes=30), min_snapshot_coverage=0.75)
    assert payload["ready"] is False
    assert payload["reason"] == "intelligence_coverage_below_threshold"
    assert payload["intelligence"]["videos_observed"] == 4
    assert payload["intelligence"]["videos_with_intelligence"] == 1
    assert payload["intelligence"]["coverage"] == 0.25
