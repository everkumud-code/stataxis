from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.operations import collection_health, intelligence_readiness
from collector.storage import Base, Channel, CollectionRun, Observation, Video


def test_collection_health_reports_unknown_without_runs():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        payload = collection_health(session, as_of=datetime(2026, 9, 15, tzinfo=UTC))
    assert payload["status"] == "unknown"
    assert payload["fresh"] is False
    assert payload["latest_run"] is None


def test_collection_health_reports_stale_failed_run():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(CollectionRun(
            started_at=datetime(2026, 9, 14, 10, tzinfo=UTC),
            finished_at=datetime(2026, 9, 14, 10, 5, tzinfo=UTC),
            status="failed",
            channels_attempted=3,
            videos_observed=20,
            error_message="upstream unavailable",
        ))
        session.commit()
        payload = collection_health(
            session,
            as_of=datetime(2026, 9, 15, tzinfo=UTC),
            stale_after_minutes=60,
        )
    assert payload["status"] == "failed"
    assert payload["fresh"] is False
    assert payload["latest_run"]["videos_observed"] == 20
    assert payload["latest_run"]["error_message"] == "upstream unavailable"


def test_collection_health_marks_recent_success_fresh():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        now = datetime(2026, 9, 15, 0, tzinfo=UTC)
        session.add(CollectionRun(
            started_at=now - timedelta(minutes=20),
            finished_at=now - timedelta(minutes=5),
            status="success",
            channels_attempted=3,
            videos_observed=75,
        ))
        session.commit()
        payload = collection_health(session, as_of=now, stale_after_minutes=60)
    assert payload["status"] == "success"
    assert payload["fresh"] is True
    assert payload["latest_run"]["age_minutes"] == 5.0


def test_intelligence_readiness_blocks_on_measurement_integrity_failure():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        now = datetime(2026, 9, 15, 0, tzinfo=UTC)
        first = Channel(youtube_channel_id="UC1", name="First")
        second = Channel(youtube_channel_id="UC2", name="Second")
        session.add_all([first, second])
        session.flush()
        video = Video(youtube_video_id="vid123", channel_id=first.id, title="Test")
        session.add(video)
        session.flush()
        session.add(Observation(video_id=video.id, channel_id=second.id, observed_at=now - timedelta(minutes=2), view_count=100))
        session.add(CollectionRun(
            started_at=now - timedelta(minutes=10),
            finished_at=now - timedelta(minutes=1),
            status="success",
            channels_attempted=2,
            videos_observed=1,
        ))
        session.commit()

        payload = intelligence_readiness(session, as_of=now, stale_after_minutes=60)

    assert payload["ready"] is False
    assert payload["reason"] == "data_integrity_failed"
    assert payload["integrity"]["ok"] is False
    assert payload["integrity"]["issue_count"] == 1
    assert payload["integrity"]["issues"][0]["code"] == "observation_channel_mismatch"


def test_intelligence_readiness_historical_cutoff_ignores_later_observations():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        cutoff = datetime(2026, 9, 15, 0, tzinfo=UTC)
        channel = Channel(youtube_channel_id="UC1", name="First")
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="vid123", channel_id=channel.id, title="Test")
        session.add(video)
        session.flush()
        session.add(Observation(video_id=video.id, channel_id=channel.id, observed_at=cutoff + timedelta(hours=1), view_count=100))
        session.commit()

        payload = intelligence_readiness(session, as_of=cutoff)

    assert payload["integrity"]["ok"] is True
    assert payload["reason"] == "no_collection_run"
