"""Time-series velocity calculations for STAXIS measurement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from metrics.engine import ObservationPoint, audience_momentum, view_velocity


@dataclass(frozen=True)
class VelocityPoint:
    """Velocity calculated for the interval ending at an observation."""

    observed_at: datetime
    view_velocity_per_minute: float | None
    audience_momentum_per_minute: float | None


def calculate_velocity(points: list[ObservationPoint]) -> list[VelocityPoint]:
    """Calculate adjacent-interval velocity without inventing missing data.

    The first observation has no prior interval, so both metrics are ``None``.
    """
    if not points:
        return []

    results = [
        VelocityPoint(
            observed_at=points[0].observed_at,
            view_velocity_per_minute=None,
            audience_momentum_per_minute=None,
        )
    ]

    for previous, current in zip(points, points[1:]):
        results.append(
            VelocityPoint(
                observed_at=current.observed_at,
                view_velocity_per_minute=view_velocity(previous, current),
                audience_momentum_per_minute=audience_momentum(previous, current),
            )
        )

    return results


def latest_velocity(points: list[ObservationPoint]) -> VelocityPoint | None:
    """Return the velocity for the latest observation interval."""
    velocities = calculate_velocity(points)
    return velocities[-1] if velocities else None
