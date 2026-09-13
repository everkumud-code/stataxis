"""Historical change calculations for STAXIS time-series measurement."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricChange:
    """Comparison between two timestamped metric values."""

    current: float | None
    previous: float | None
    delta: float | None
    percent_change: float | None
    sufficient_data: bool


def compare_metric(
    previous: float | int | None,
    current: float | int | None,
) -> MetricChange:
    """Compare two metric values without inventing missing observations.

    Percent change is undefined when the previous value is missing or zero.
    """
    if previous is None or current is None:
        return MetricChange(
            current=float(current) if current is not None else None,
            previous=float(previous) if previous is not None else None,
            delta=None,
            percent_change=None,
            sufficient_data=False,
        )

    current_value = float(current)
    previous_value = float(previous)
    delta = current_value - previous_value
    percent_change = None
    if previous_value != 0:
        percent_change = (delta / previous_value) * 100

    return MetricChange(
        current=current_value,
        previous=previous_value,
        delta=delta,
        percent_change=percent_change,
        sufficient_data=True,
    )
