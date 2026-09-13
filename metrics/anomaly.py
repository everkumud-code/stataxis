"""Robust historical anomaly detection for STAXIS time-series metrics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median


@dataclass(frozen=True)
class AnomalyPoint:
    """Anomaly assessment for one timestamped metric observation."""

    observed_at: datetime
    value: float | None
    baseline: float | None
    mad: float | None
    robust_z_score: float | None
    is_anomaly: bool
    direction: str | None
    sufficient_data: bool


def _robust_scale(values: list[float]) -> float:
    """Return median absolute deviation scaled to normal-score units."""
    center = median(values)
    return median([abs(value - center) for value in values]) * 1.4826


def detect_anomalies(
    points: list[tuple[datetime, float | None]],
    *,
    minimum_points: int = 5,
    z_threshold: float = 3.5,
    window: int | None = None,
) -> list[AnomalyPoint]:
    """Detect unusual observations against a prior robust baseline.

    The current observation is never included in its own baseline. Missing values
    remain unavailable rather than being interpreted as zero. A zero historical
    MAD is treated as a constant baseline: any different value is anomalous.
    """
    if minimum_points < 1:
        raise ValueError("minimum_points must be at least 1")
    if z_threshold <= 0:
        raise ValueError("z_threshold must be positive")
    if window is not None and window < minimum_points:
        raise ValueError("window must be at least minimum_points")

    results: list[AnomalyPoint] = []

    for index, (observed_at, value) in enumerate(points):
        history = [item_value for _, item_value in points[:index] if item_value is not None]
        if window is not None:
            history = history[-window:]

        if value is None or len(history) < minimum_points:
            results.append(
                AnomalyPoint(
                    observed_at=observed_at,
                    value=value,
                    baseline=median(history) if history else None,
                    mad=_robust_scale(history) if history else None,
                    robust_z_score=None,
                    is_anomaly=False,
                    direction=None,
                    sufficient_data=False,
                )
            )
            continue

        baseline = median(history)
        mad = _robust_scale(history)
        difference = value - baseline

        if mad == 0:
            robust_z_score = float("inf") if difference != 0 else 0.0
        else:
            robust_z_score = difference / mad

        is_anomaly = abs(robust_z_score) >= z_threshold
        direction = None
        if is_anomaly:
            direction = "positive" if difference > 0 else "negative"

        results.append(
            AnomalyPoint(
                observed_at=observed_at,
                value=float(value),
                baseline=float(baseline),
                mad=float(mad),
                robust_z_score=float(robust_z_score),
                is_anomaly=is_anomaly,
                direction=direction,
                sufficient_data=True,
            )
        )

    return results


def latest_anomaly(
    points: list[tuple[datetime, float | None]],
    *,
    minimum_points: int = 5,
    z_threshold: float = 3.5,
    window: int | None = None,
) -> AnomalyPoint | None:
    """Return the anomaly assessment for the latest supplied observation."""
    results = detect_anomalies(
        points,
        minimum_points=minimum_points,
        z_threshold=z_threshold,
        window=window,
    )
    return results[-1] if results else None
