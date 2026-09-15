"""Transparent STX Index v0 signal fusion for StatAxis."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class STXSignals:
    """Normalized 0-100 signals used by the STX Index."""

    audience: float | None = None
    growth: float | None = None
    view_velocity: float | None = None
    momentum: float | None = None
    acceleration: float | None = None
    consistency: float | None = None
    engagement: float | None = None
    competitive_position: float | None = None
    anomaly_event: float | None = None


@dataclass(frozen=True)
class STXIndexResult:
    """Explainable STX Index result with coverage and component scores."""

    score: float | None
    confidence: float
    available_signals: int
    component_scores: dict[str, float]


# Provisional v0 weights. These are explicit calibration starting points,
# not claims of empirical truth.
WEIGHTS: dict[str, float] = {
    "audience": 0.23,
    "growth": 0.14,
    "view_velocity": 0.10,
    "momentum": 0.14,
    "acceleration": 0.09,
    "consistency": 0.09,
    "engagement": 0.10,
    "competitive_position": 0.06,
    "anomaly_event": 0.05,
}


def _validate_signal(value: float | None) -> float | None:
    if value is None:
        return None
    if not 0 <= value <= 100:
        raise ValueError("STX signals must be between 0 and 100")
    return value


def calculate_stx_index(signals: STXSignals) -> STXIndexResult:
    """Fuse available normalized signals without treating missing data as zero."""
    raw = {
        "audience": signals.audience,
        "growth": signals.growth,
        "view_velocity": signals.view_velocity,
        "momentum": signals.momentum,
        "acceleration": signals.acceleration,
        "consistency": signals.consistency,
        "engagement": signals.engagement,
        "competitive_position": signals.competitive_position,
        "anomaly_event": signals.anomaly_event,
    }
    available = {
        name: _validate_signal(value)
        for name, value in raw.items()
        if value is not None
    }
    if not available:
        return STXIndexResult(None, 0.0, 0, {})

    available_weight = sum(WEIGHTS[name] for name in available)
    component_scores = {
        name: value * WEIGHTS[name] / available_weight
        for name, value in available.items()
    }
    score = sum(component_scores.values())
    confidence = round(available_weight / sum(WEIGHTS.values()) * 100, 6)
    return STXIndexResult(
        score=score,
        confidence=confidence,
        available_signals=len(available),
        component_scores=component_scores,
    )
