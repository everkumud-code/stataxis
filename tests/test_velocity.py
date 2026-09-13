from datetime import UTC, datetime, timedelta

from metrics.engine import ObservationPoint
from metrics.velocity import calculate_velocity, latest_velocity


def test_calculate_velocity_builds_adjacent_intervals():
    start = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
    points = [
        ObservationPoint(observed_at=start, view_count=1000, concurrent_viewers=500),
        ObservationPoint(
            observed_at=start + timedelta(minutes=2),
            view_count=1200,
            concurrent_viewers=600,
        ),
        ObservationPoint(
            observed_at=start + timedelta(minutes=5),
            view_count=1500,
            concurrent_viewers=750,
        ),
    ]

    result = calculate_velocity(points)

    assert len(result) == 3
    assert result[0].view_velocity_per_minute is None
    assert result[0].audience_momentum_per_minute is None
    assert result[1].view_velocity_per_minute == 100.0
    assert result[1].audience_momentum_per_minute == 50.0
    assert result[2].view_velocity_per_minute == 100.0
    assert result[2].audience_momentum_per_minute == 50.0


def test_velocity_preserves_missing_measurements():
    start = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
    points = [
        ObservationPoint(observed_at=start, view_count=1000),
        ObservationPoint(observed_at=start + timedelta(minutes=1), view_count=1100),
        ObservationPoint(
            observed_at=start + timedelta(minutes=2),
            view_count=None,
            concurrent_viewers=300,
        ),
    ]

    result = calculate_velocity(points)

    assert result[1].view_velocity_per_minute == 100.0
    assert result[2].view_velocity_per_minute is None
    assert result[2].audience_momentum_per_minute is None


def test_latest_velocity_returns_latest_interval():
    start = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
    points = [
        ObservationPoint(observed_at=start, view_count=100),
        ObservationPoint(observed_at=start + timedelta(minutes=5), view_count=600),
    ]

    result = latest_velocity(points)

    assert result is not None
    assert result.observed_at == start + timedelta(minutes=5)
    assert result.view_velocity_per_minute == 100.0


def test_latest_velocity_returns_none_for_empty_series():
    assert latest_velocity([]) is None
