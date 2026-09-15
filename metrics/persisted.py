"""Bridge persisted observations into the pure STX intelligence pipeline."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from collector.storage import Observation, Video
from metrics.engine import ObservationPoint
from metrics.pipeline import IntelligenceSnapshot, build_intelligence_snapshot
from metrics.timeseries import compare_metric


def _utc(value: datetime | None) -> datetime | None:
    """Normalize database timestamps to explicit UTC for deterministic provenance."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def build_persisted_video_snapshot(
    session: Session,
    video_id: int,
    *,
    data: list[str] | None = None,
    limit: int = 25,
) -> IntelligenceSnapshot:
    """Build an explainable STX snapshot from observations already in storage.

    The adapter is read-only and never invents change signals from a single
    observation. Observations are ordered chronologically before measurement.
    """
    if limit < 2:
        raise ValueError("limit must be at least 2")

    video = session.get(Video, video_id)
    if video is None:
        raise ValueError(f"video {video_id} not found")

    rows = (
        session.query(Observation)
        .filter(Observation.video_id == video_id)
        .order_by(Observation.observed_at.desc())
        .limit(limit)
        .all()
    )
    observations = [
        ObservationPoint(
            observed_at=_utc(row.observed_at),
            view_count=row.view_count,
            concurrent_viewers=row.concurrent_viewers,
            like_count=row.like_count,
            comment_count=row.comment_count,
        )
        for row in reversed(rows)
    ]

    first = observations[0] if observations else None
    last = observations[-1] if observations else None
    has_change_window = len(observations) >= 2
    audience_change = compare_metric(
        first.concurrent_viewers if has_change_window and first else None,
        last.concurrent_viewers if has_change_window and last else None,
    )
    growth_change = compare_metric(
        first.view_count if has_change_window and first else None,
        last.view_count if has_change_window and last else None,
    )

    snapshot_data = list(data or [])
    if not snapshot_data and video.title:
        snapshot_data.append(video.title)

    return build_intelligence_snapshot(
        data=snapshot_data,
        observations=observations,
        audience_change=audience_change,
        growth_change=growth_change,
    )
