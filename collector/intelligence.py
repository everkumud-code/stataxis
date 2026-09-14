"""Persisted-observation intelligence orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from collector.storage import Observation
from metrics.persistence import persist_video_intelligence


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
    """Build and durably store STX intelligence for persisted videos."""
    video_ids = [row[0] for row in session.query(Observation.video_id).distinct().all()]
    processed = snapshots = errors = 0
    for video_id in video_ids:
        processed += 1
        try:
            persist_video_intelligence(session, video_id, limit=limit_per_video)
            snapshots += 1
        except (ValueError, RuntimeError):
            session.rollback()
            errors += 1
    return IntelligenceRunResult(processed, snapshots, errors)
