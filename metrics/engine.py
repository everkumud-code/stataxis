"""Pure STAXIS derived-metric calculations.

The functions in this module do not access YouTube or the database. They operate
only on timestamped observations, which keeps the measurement methodology
reproducible and easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ObservationPoint:
    """Minimal point needed for time-series calculations."""

    observed_at: datetime
    view_count: int | None = None
    concurrent_viewers: int | None = None
    like_count: int | None = None
    comment_count: int | None = None


def _rate(delta: int | None, elapsed_seconds: float) -> float | None:
    if delta is None or elapsed_seconds <= 0:
        return None
    return delta / elapsed_seconds


def view_velocity(previous: ObservationPoint, current: ObservationPoint) -> float | None:
    """Return views gained per minute between two observations."""
    elapsed = (current.observed_at - previous.observed_at).total_seconds()
    if previous.view_count is None or current.view_count is None:
        return None
    rate = _rate(current.view_count - previous.view_count, elapsed)
    return rate * 60 if rate is not None else None


def audience_momentum(previous: ObservationPoint, current: ObservationPoint) -> float | None:
    """Return concurrent-viewer change per minute between two observations."""
    elapsed = (current.observed_at - previous.observed_at).total_seconds()
    if previous.concurrent_viewers is None or current.concurrent_viewers is None:
        return None
    rate = _rate(
        current.concurrent_viewers - previous.concurrent_viewers,
        elapsed,
    )
    return rate * 60 if rate is not None else None


def engagement_rate(previous: ObservationPoint, current: ObservationPoint) -> float | None:
    """Return likes plus comments gained per minute between observations."""
    elapsed = (current.observed_at - previous.observed_at).total_seconds()
    if (
        previous.like_count is None
        or current.like_count is None
        or previous.comment_count is None
        or current.comment_count is None
    ):
        return None
    rate = _rate(
        (current.like_count - previous.like_count)
        + (current.comment_count - previous.comment_count),
        elapsed,
    )
    return rate * 60 if rate is not None else None


def average(values: list[int | float | None]) -> float | None:
    """Return the arithmetic mean of available numeric values."""
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


def peak(values: list[int | float | None]) -> int | float | None:
    """Return the highest available value."""
    usable = [value for value in values if value is not None]
    return max(usable) if usable else None
