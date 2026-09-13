"""Time-series acceleration calculations for STAXIS measurement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from metrics.engine import ObservationPoint
from metrics.velocity import VelocityPoint, calculate_velocity


@dataclass(frozen=True)
class AccelerationPoint:
    """Acceleration calculated for the interval ending at an observation."""

    observed_at: datetime
    view_acceleration_per_minute_squared: float | None
    audience_acceleration_per_minute_squared: float | None


def _acceleration(
    previous: float | None,
    current: float | None,
    elapsed_seconds: float,
) -> float | None:
    """Return change in rate per minute, preserving unavailable data."""
    if previous is None or current is None or elapsed_seconds <= 0:
        return None
    return ((current - previous) / elapsed_seconds) * 60


def _interval_seconds(previous: VelocityPoint, current: VelocityPoint) -> float:
    return (current.observed_at - previous.observed_at).total_seconds()


def calculate_acceleration(points: list[ObservationPoint]) -> list[AccelerationPoint]:
    """Calculate adjacent changes in velocity without inventing missing data.

    At least three observations are required for the first acceleration value.
    Each result describes the change in velocity over the interval ending at
    the current observation. Irregular intervals are handled using timestamps.
    """
    velocities = calculate_velocity(points)
    if len(velocities) < 2:
        return [
            AccelerationPoint(
                observed_at=point.observed_at,
                view_acceleration_per_minute_squared=None,
                audience_acceleration_per_minute_squared=None,
            )
            for point in velocities
        ]

    results = [
        AccelerationPoint(
            observed_at=velocities[0].observed_at,
            view_acceleration_per_minute_squared=None,
            audience_acceleration_per_minute_squared=None,
        )
    ]

    for previous, current in pairwise(velocities):
        elapsed = _interval_seconds(previous, current)
        results.append(
            AccelerationPoint(
                observed_at=current.observed_at,
                view_acceleration_per_minute_squared=_acceleration(
                    previous.view_velocity_per_minute,
                    current.view_velocity_per_minute,
                    elapsed,
                ),
                audience_acceleration_per_minute_squared=_acceleration(
                    previous.audience_momentum_per_minute,
                    current.audience_momentum_per_minute,
                    elapsed,
                ),
            )
        )

    return results


def latest_acceleration(points: list[ObservationPoint]) -> AccelerationPoint | None:
    """Return the acceleration for the latest available observation interval."""
    accelerations = calculate_acceleration(points)
    return accelerations[-1] if accelerations else None
