"""Bridge STX Index signals into an explainable StatAxis View."""

from __future__ import annotations

from dataclasses import dataclass

from metrics.stx_index import STXIndexResult, STXSignals, calculate_stx_index
from metrics.view import Signal, StatAxisView, build_stat_axis_view


@dataclass(frozen=True)
class FusedIntelligence:
    """Combined index and viewpoint produced from the same signal snapshot."""

    index: STXIndexResult
    view: StatAxisView


def _to_direction(value: float | None) -> str:
    if value is None:
        return "neutral"
    if value >= 60:
        return "positive"
    if value <= 40:
        return "negative"
    return "neutral"


def build_fused_intelligence(
    data: list[str],
    signals: STXSignals,
) -> FusedIntelligence:
    """Produce one consistent STX Index and conservative StatAxis View."""
    index = calculate_stx_index(signals)
    signal_map = {
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
    view_signals = [
        Signal(name=name, direction=_to_direction(value), strength=value)
        for name, value in signal_map.items()
        if value is not None
    ]
    view = build_stat_axis_view(data, view_signals, index.confidence)
    return FusedIntelligence(index=index, view=view)
