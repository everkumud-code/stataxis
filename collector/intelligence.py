"""Persisted-observation intelligence orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from collector.storage import CollectionRun, Observation, Video
from metrics.persisted import build_persisted_video_snapshot


@dataclass(frozen=True)
class IntelligenceRunResult:
    videos_processed: int
    snapshots_built: int
    errors: int


def process_persisted_observations(
    session: Session,
    *,
    limit_per_video: int = 25,
) -> IntelligenceRunResult:
    """Build STX intelligence for videos having persisted observations.

    This first production bridge is deliberately read-only with respect to
    measurements and produces deterministic snapshots in memory. A later
    persistence layer can store snapshots without changing this contract.
    """
    video_ids = [
        row[0]
        for row in session.query(Observation.video_id).distinct().all()
    ]
    processed = 0
    snapshots = 0
    errors = 0
    for video_id in video_ids:
        processed += 1
        try:
            build_persisted_video_snapshot(
                session,
                video_id,
                limit=limit_per_video,
            )
            snapshots += 1
        except (ValueError, RuntimeError):
            errors += 1
    return IntelligenceRunResult(processed, snapshots, errors)


def create_collection_run(started_at: datetime | None = None) -> CollectionRun:
    """Create an in-memory collection-run record for orchestration callers."""
    return CollectionRun(
        started_at=started_at or datetime.now(UTC),
        status="INTELLIGENCE_PENDING",
    )
