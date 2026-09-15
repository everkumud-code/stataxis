"""Read-only operational health accessors for production collection runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from collector.integrity import audit_database
from collector.storage import CollectionRun, Observation
from metrics.persistence import IntelligenceSnapshotRecord


def collection_health(session: Session, *, as_of: datetime | None = None, stale_after_minutes: int = 360) -> dict[str, Any]:
    """Return the latest collection-run state and a deterministic freshness flag."""
    if stale_after_minutes <= 0:
        raise ValueError("stale_after_minutes must be positive")
    resolved_as_of = _utc(as_of or datetime.now(UTC))
    run = session.execute(select(CollectionRun).order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc()).limit(1)).scalar_one_or_none()
    if run is None:
        return {"status": "unknown", "fresh": False, "as_of": resolved_as_of.isoformat(), "latest_run": None, "stale_after_minutes": stale_after_minutes}
    started_at = _utc(run.started_at)
    finished_at = _utc(run.finished_at) if run.finished_at else None
    reference_at = finished_at or started_at
    age_minutes = max(0.0, (resolved_as_of - reference_at).total_seconds() / 60)
    fresh = reference_at <= resolved_as_of and run.status == "success" and age_minutes <= stale_after_minutes
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


def intelligence_readiness(session: Session, *, as_of: datetime | None = None, stale_after_minutes: int = 360, min_snapshot_coverage: float = 1.0) -> dict[str, Any]:
    """Assess collection freshness, persisted-data integrity, and STX coverage."""
    if not 0.0 <= min_snapshot_coverage <= 1.0:
        raise ValueError("min_snapshot_coverage must be between 0 and 1")
    resolved_as_of = _utc(as_of or datetime.now(UTC))
    health = collection_health(session, as_of=resolved_as_of, stale_after_minutes=stale_after_minutes)
    integrity = audit_database(session, as_of=as_of)
    integrity_payload = {
        "ok": integrity.ok,
        "checked_channels": integrity.checked_channels,
        "checked_videos": integrity.checked_videos,
        "checked_observations": integrity.checked_observations,
        "checked_collection_runs": integrity.checked_collection_runs,
        "issue_count": len(integrity.issues),
        "issues": [{"code": issue.code, "message": issue.message} for issue in integrity.issues],
    }
    run = health["latest_run"]
    if not integrity.ok:
        observed = 0 if run is None else max(0, int(run["videos_observed"]))
        return {
            "ready": False,
            "reason": "data_integrity_failed",
            "collection": health,
            "integrity": integrity_payload,
            "intelligence": {"videos_observed": observed, "videos_with_intelligence": 0, "coverage": 0.0, "min_snapshot_coverage": min_snapshot_coverage},
        }
    if run is None:
        return {"ready": False, "reason": "no_collection_run", "collection": health, "integrity": integrity_payload, "intelligence": {"videos_observed": 0, "videos_with_intelligence": 0, "coverage": 0.0, "min_snapshot_coverage": min_snapshot_coverage}}
    observed = max(0, int(run["videos_observed"]))
    run_started_at = datetime.fromisoformat(run["started_at"])
    observed_video_ids = (
        select(distinct(Observation.video_id))
        .where(Observation.observed_at >= run_started_at)
        .where(Observation.observed_at <= resolved_as_of)
        .subquery()
    )
    query = (
        select(func.count(distinct(IntelligenceSnapshotRecord.video_id)))
        .select_from(IntelligenceSnapshotRecord)
        .where(IntelligenceSnapshotRecord.video_id.in_(select(observed_video_ids.c.video_id)))
        .where(IntelligenceSnapshotRecord.generated_at >= run_started_at)
        .where(IntelligenceSnapshotRecord.generated_at <= resolved_as_of)
    )
    with_intelligence = int(session.execute(query).scalar_one() or 0)
    coverage = min(1.0, with_intelligence / observed) if observed else 0.0
    ready = bool(health["fresh"] and observed > 0 and coverage >= min_snapshot_coverage)
    reason = "ready"
    if not health["fresh"]:
        reason = "collection_not_fresh"
    elif observed == 0:
        reason = "no_videos_observed"
    elif coverage < min_snapshot_coverage:
        reason = "intelligence_coverage_below_threshold"
    return {
        "ready": ready,
        "reason": reason,
        "collection": health,
        "integrity": integrity_payload,
        "intelligence": {
            "videos_observed": observed,
            "videos_with_intelligence": with_intelligence,
            "coverage": round(coverage, 4),
            "min_snapshot_coverage": min_snapshot_coverage,
        },
    }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
