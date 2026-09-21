"""Persisted-observation intelligence orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func
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
    since: datetime | None = None,
) -> IntelligenceRunResult:
    """Build and durably store STX intelligence for videos with a change window.

    With ``since`` only videos observed at or after that moment are processed. A video
    with no new observation would produce an identical snapshot, so re-processing every
    video on every pass only wastes database round trips and grows the snapshot table.
    """
    query = session.query(Observation.video_id)
    if since is not None:
        query = query.filter(Observation.observed_at >= since)
    video_ids = [row[0] for row in query.distinct().all()]

    # One grouped query per chunk instead of one COUNT query per video.
    counts: dict[int, int] = {}
    for start in range(0, len(video_ids), 1000):
        chunk = video_ids[start:start + 1000]
        counts.update(
            session.query(Observation.video_id, func.count(Observation.id))
            .filter(Observation.video_id.in_(chunk))
            .group_by(Observation.video_id)
            .all()
        )

    processed = snapshots = errors = 0
    for video_id in video_ids:
        processed += 1
        if counts.get(video_id, 0) < 2:
            continue
        try:
            persist_video_intelligence(session, video_id, limit=limit_per_video)
            snapshots += 1
        except (ValueError, RuntimeError):
            session.rollback()
            errors += 1
    return IntelligenceRunResult(processed, snapshots, errors)


def persist_intelligence_snapshot(
    session: Session,
    video_id: int,
    *,
    limit: int = 25,
):
    """Backward-compatible facade for callers using the legacy collector API."""
    return persist_video_intelligence(session, video_id, limit=limit)
