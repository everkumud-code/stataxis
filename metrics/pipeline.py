"""Deterministic measurement-to-intelligence pipeline for StatAxis."""

from __future__ import annotations

from dataclasses import dataclass

from metrics.acceleration import latest_acceleration
from metrics.competition import CompetitiveStanding
from metrics.explain import SignalContribution, explain_index
from metrics.fusion import FusedIntelligence, build_fused_intelligence
from metrics.signal_factory import build_stx_signals
from metrics.timeseries import MetricChange
from metrics.velocity import latest_velocity
from metrics.engine import ObservationPoint


@dataclass(frozen=True)
class IntelligenceSnapshot:
    """Complete explainable output produced from one measured snapshot."""

    intelligence: FusedIntelligence
    contributions: tuple[SignalContribution, ...]


def build_intelligence_snapshot(
    data: list[str],
    observations: list[ObservationPoint],
    audience_change: MetricChange,
    growth_change: MetricChange,
    standing: CompetitiveStanding | None = None,
) -> IntelligenceSnapshot:
    """Turn measured changes and timestamped observations into one STX snapshot.

    The function is intentionally deterministic and side-effect free: collection
    and persistence remain outside the metric layer, while every derived output
    is calculated from the supplied measurements only.
    """
    velocity = latest_velocity(observations)
    acceleration = latest_acceleration(observations)
    signals = build_stx_signals(
        audience_change=audience_change,
        growth_change=growth_change,
        velocity=velocity,
        acceleration=acceleration,
        standing=standing,
        observations=observations,
    )
    intelligence = build_fused_intelligence(data, signals)
    contributions = explain_index(intelligence.index)
    return IntelligenceSnapshot(
        intelligence=intelligence,
        contributions=contributions,
    )
