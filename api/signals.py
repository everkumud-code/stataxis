"""Dashboard-ready derived signal accessors from persisted observations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from collector.storage import Channel, Observation
from metrics.engine import ObservationPoint, audience_momentum, view_velocity
from metrics.eligibility import analysis_observation_clause


def channel_signals(
    session: Session,
    channel_id: int,
    *,
    window_hours: int = 24,
) -> dict[str, Any] | None:
    """Return recent deterministic momentum signals for one channel.

    View velocity is based on consecutive persisted cumulative view counts.
    Audience momentum is based on consecutive concurrent-viewer observations when
    those observations exist. No audience size is inferred from cumulative views.
    """
    channel = session.get(Channel, channel_id)
    if channel is None:
        return None

    now = datetime.now(UTC)
    start = now - timedelta(hours=max(1, min(int(window_hours), 168)))
    rows = session.execute(
        select(
            Observation.observed_at,
            Observation.view_count,
            Observation.concurrent_viewers,
            Observation.is_live,
        )
        .where(
            Observation.channel_id == channel_id,
            Observation.observed_at >= start,
            Observation.observed_at <= now,
            analysis_observation_clause(),
        )
        .order_by(Observation.observed_at.asc(), Observation.id.asc())
    ).all()

    points = [
        ObservationPoint(
            observed_at=_utc(observed_at),
            view_count=view_count,
            concurrent_viewers=concurrent_viewers,
        )
        for observed_at, view_count, concurrent_viewers, _ in rows
    ]

    velocity_values: list[float] = []
    momentum_values: list[float] = []
    for previous, current in zip(points, points[1:]):
        velocity = view_velocity(previous, current)
        if velocity is not None:
            velocity_values.append(velocity)
        momentum = audience_momentum(previous, current)
        if momentum is not None:
            momentum_values.append(momentum)

    latest_velocity = velocity_values[-1] if velocity_values else None
    avg_velocity = sum(velocity_values) / len(velocity_values) if velocity_values else None
    latest_momentum = momentum_values[-1] if momentum_values else None
    avg_momentum = sum(momentum_values) / len(momentum_values) if momentum_values else None

    return {
        "channel_id": channel.id,
        "name": channel.name,
        "window_hours": max(1, min(int(window_hours), 168)),
        "observation_count": len(points),
        "view_velocity_per_minute": latest_velocity,
        "average_view_velocity_per_minute": avg_velocity,
        "audience_momentum_per_minute": latest_momentum,
        "average_audience_momentum_per_minute": avg_momentum,
        "momentum_direction": _direction(avg_momentum),
        "live_observation_count": sum(1 for row in rows if row[3]),
        "as_of": now.isoformat(),
    }


def _direction(value: float | None) -> str:
    if value is None:
        return "insufficient_data"
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "flat"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
