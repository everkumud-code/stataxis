"""Convert measured StatAxis metrics into normalized STX signals."""

from __future__ import annotations

from metrics.competition import CompetitiveStanding
from metrics.stx_index import STXSignals
from metrics.timeseries import MetricChange
from metrics.velocity import VelocityPoint


def _bounded(value: float) -> float:
    return max(0.0, min(100.0, value))


def _change_signal(change: MetricChange) -> float | None:
    if not change.sufficient_data or change.percent_change is None:
        return None
    # +/-50% change maps to the 0-100 directional scale.
    return _bounded(50.0 + change.percent_change)


def _velocity_signal(value: float | None) -> float | None:
    if value is None:
        return None
    # 0 is neutral; +/-100 units/minute map to the directional extremes.
    return _bounded(50.0 + value / 2.0)


def _standing_signal(standing: CompetitiveStanding | None) -> float | None:
    if standing is None or standing.rank is None or standing.total_channels <= 0:
        return None
    if standing.total_channels == 1:
        return 100.0
    return 100.0 * (standing.total_channels - standing.rank) / (standing.total_channels - 1)


def build_stx_signals(
    audience_change: MetricChange,
    growth_change: MetricChange,
    latest_velocity: VelocityPoint | None,
    standing: CompetitiveStanding | None = None,
) -> STXSignals:
    """Build a real signal snapshot from measured changes and competition data.

    Missing source metrics remain missing rather than being converted to zero.
    """
    momentum = _velocity_signal(
        latest_velocity.audience_momentum_per_minute if latest_velocity else None
    )
    acceleration = None
    if latest_velocity is not None and latest_velocity.audience_momentum_per_minute is not None:
        acceleration = _velocity_signal(latest_velocity.audience_momentum_per_minute)

    return STXSignals(
        audience=_change_signal(audience_change),
        growth=_change_signal(growth_change),
        momentum=momentum,
        acceleration=acceleration,
        competitive_position=_standing_signal(standing),
    )
