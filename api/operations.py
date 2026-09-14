"""Read-only operational health accessors for production collection runs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from collector.storage import CollectionRun


def collection_health(
    session: Session,
    *,
    as_of: datetime | None = None,
    stale_after_minutes: int = 360,
) -> dict[str, Any]:
    """Return the latest collection-run state and a deterministic freshness flag."""
    if stale_after_minutes <= 0:
        raise ValueError("stale_after_minutes must be positive")
    resolved_as_of = _utc(as_of or datetime.now(UTC))
    run = session.execute(
        select(CollectionRun).order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc()).limit(1)
    ).scalar_one_or_none()
    if run is None:
        return {
            "status": "unknown",
            "fresh": False,
            "as_of": resolved_as_of.isoformat(),
            "latest_run": None,
            "stale_after_minutes": stale_after_minutes,
        }

    started_at = _utc(run.started_at)
    finished_at = _utc(run.finished_at) if run.finished_at else None
    reference_at = finished_at or started_at
    age_minutes = max(0.0, (resolved_as_of - reference_at).total_seconds() / 60)
    fresh = run.status == "success" and age_minutes <= stale_after_minutes
    return {
        "status": run.status,
        "fresh": fresh,
        "as_of": resolved_as_of.isoformat(),
        "latest_run": {
            "id": run.id,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat() if finished_at else None,
            "status": run.status,
            "channels_attempted": run.channels_attempted,
            "videos_observed": run.videos_observed,
            "error_message": run.error_message,
            "age_minutes": round(age_minutes, 2),
        },
        "stale_after_minutes": stale_after_minutes,
    }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
