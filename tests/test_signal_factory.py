from datetime import datetime, timedelta, timezone

from metrics.acceleration import AccelerationPoint
from metrics.competition import CompetitiveStanding
from metrics.engine import ObservationPoint
from metrics.signal_factory import build_stx_signals
from metrics.timeseries import compare_metric
from metrics.velocity import VelocityPoint


def test_build_stx_signals_maps_measured_inputs():
    now = datetime.now(timezone.utc)
    velocity = VelocityPoint(now, 20.0, 10.0)
    acceleration = AccelerationPoint(now, 4.0, -2.0)
    standing = CompetitiveStanding("a", "A", 1000, 1, 1.0, None, None, None, None, 0, None, 10.0, 1)

    result = build_stx_signals(
        compare_metric(100, 120),
        compare_metric(100, 130),
        velocity,
        acceleration,
        standing,
    )

    assert result.audience == 70
    assert result.growth == 80
    assert result.momentum == 55
    assert result.acceleration == 48
    assert result.consistency is None
    assert result.competitive_position == 100


def test_consistency_reflects_latest_velocity_direction():
    now = datetime.now(timezone.utc)
    observations = [
        ObservationPoint(now, view_count=100),
        ObservationPoint(now + timedelta(minutes=1), view_count=110),
        ObservationPoint(now + timedelta(minutes=2), view_count=105),
        ObservationPoint(now + timedelta(minutes=3), view_count=115),
    ]
    result = build_stx_signals(
        compare_metric(100, 115),
        compare_metric(100, 115),
        VelocityPoint(now, 10.0, None),
        observations=observations,
    )
    assert result.consistency == 66.66666666666667


def test_consistency_missing_with_insufficient_velocity_history():
    now = datetime.now(timezone.utc)
    observations = [
        ObservationPoint(now, view_count=100),
        ObservationPoint(now + timedelta(minutes=1), view_count=110),
    ]
    result = build_stx_signals(
        compare_metric(100, 110),
        compare_metric(100, 110),
        VelocityPoint(now, 10.0, None),
        observations=observations,
    )
    assert result.consistency is None


def test_missing_measurements_remain_missing():
    now = datetime.now(timezone.utc)
    result = build_stx_signals(
        compare_metric(None, 120),
        compare_metric(100, 100),
        VelocityPoint(now, None, None),
    )
    assert result.audience is None
    assert result.growth == 50
    assert result.momentum is None
    assert result.acceleration is None
    assert result.consistency is None
    assert result.competitive_position is None
