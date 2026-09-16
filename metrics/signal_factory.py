"""Convert measured StatAxis metrics into normalized STX signals."""

from __future__ import annotations

from metrics.acceleration import AccelerationPoint
from metrics.anomaly import latest_anomaly
from metrics.competition import CompetitiveStanding
from metrics.engine import ObservationPoint
from metrics.stx_index import STXSignals
from metrics.timeseries import MetricChange
from metrics.velocity import VelocityPoint, calculate_velocity


def _bounded(value: float) -> float:
    return max(0.0, min(100.0, value))


def _change_signal(change: MetricChange | None) -> float | None:
    if change is None or not change.sufficient_data or change.percent_change is None:
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


def _consistency_signal(observations: list[ObservationPoint]) -> float | None:
    """Score how consistently view velocity has kept its latest direction."""
    velocities = [point.view_velocity_per_minute for point in calculate_velocity(observations)]
    usable = [value for value in velocities if value is not None and value != 0]
    if len(usable) < 2:
        return None
    latest_sign = 1 if usable[-1] > 0 else -1
    matching = sum((1 if value > 0 else -1) == latest_sign for value in usable)
    return _bounded(100.0 * matching / len(usable))


def _anomaly_signal(observations: list[ObservationPoint]) -> float | None:
    """Convert a robust historical view anomaly into a bounded event signal."""
    if not observations:
        return None
    points = [(point.observed_at, point.view_count) for point in observations]
    anomaly = latest_anomaly(points, minimum_points=5, z_threshold=3.5)
    if anomaly is None or not anomaly.sufficient_data or anomaly.robust_z_score is None:
        return None
    return _bounded(50.0 + anomaly.robust_z_score * 10.0)


def build_stx_signals(
    audience_change: MetricChange | None,
    growth_change: MetricChange | None,
    velocity: VelocityPoint | None,
    acceleration: AccelerationPoint | None = None,
    standing: CompetitiveStanding | None = None,
    observations: list[ObservationPoint] | None = None,
) -> STXSignals:
    """Build a real v0 signal snapshot from measured metrics.

    Missing source metrics remain missing rather than being converted to zero.
    Cross-platform engagement is intentionally excluded from STX Index v0.
    Anomaly/event is derived only when a sufficient persisted history exists.
    """
    observations = observations or []
    return STXSignals(
        audience=_change_signal(audience_change),
        growth=_change_signal(growth_change),
        view_velocity=_rate_signal(velocity.view_velocity_per_minute if velocity else None, 100.0),
        momentum=_rate_signal(velocity.audience_momentum_per_minute if velocity else None, 2.0),
        acceleration=_rate_signal(
            acceleration.audience_acceleration_per_minute_squared if acceleration else None,
            1.0,
        ),
        consistency=_consistency_signal(observations),
        competitive_position=_standing_signal(standing),
        anomaly_event=_anomaly_signal(observations),
    )
