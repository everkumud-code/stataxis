"""Convert measured StatAxis metrics into normalized STX signals."""

from __future__ import annotations

from metrics.acceleration import AccelerationPoint
from metrics.competition import CompetitiveStanding
from metrics.stx_index import STXSignals
from metrics.timeseries import MetricChange
from metrics.velocity import VelocityPoint


def _bounded(value: float) -> float:
    return max(0.0, min(100.0, value))


def _change_signal(change: MetricChange) -> float | None:
    if not change.sufficient_data or change.percent_change is None:
        return None
    return _bounded(50.0 + change.percent_change)


def _rate_signal(value: float | None, scale: float) -> float | None:
    if value is None:
        return None
    return _bounded(50.0 + value / scale)


def _standing_signal(standing: CompetitiveStanding | None) -> float | None:
    if standing is None or standing.rank is None:
        return None
    return _bounded(100.0 / standing.rank)


def build_stx_signals(
    audience_change: MetricChange,
    growth_change: MetricChange,
    velocity: VelocityPoint | None,
    acceleration: AccelerationPoint | None = None,
    standing: CompetitiveStanding | None = None,
) -> STXSignals:
    """Build a real signal snapshot from measured metrics.

    Missing source metrics remain missing rather than being converted to zero.
    """
    return STXSignals(
        audience=_change_signal(audience_change),
        growth=_change_signal(growth_change),
        momentum=_rate_signal(
            velocity.audience_momentum_per_minute if velocity else None,
            2.0,
        ),
        acceleration=_rate_signal(
            acceleration.audience_acceleration_per_minute_squared if acceleration else None,
            1.0,
        ),
        competitive_position=_standing_signal(standing),
    )
