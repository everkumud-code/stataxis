from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.operations import collection_health
from collector.storage import Base, CollectionRun


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
