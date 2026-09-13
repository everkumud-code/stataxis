from datetime import UTC, datetime, timedelta

from metrics.acceleration import calculate_acceleration, latest_acceleration
from metrics.engine import ObservationPoint


def test_acceleration_requires_three_observations():
    start = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
    points = [
        ObservationPoint(start, view_count=1000),
        ObservationPoint(start + timedelta(minutes=5), view_count=1500),
    ]
    result = calculate_acceleration(points)
    assert len(result) == 2
    assert result[-1].view_acceleration_per_minute_squared is None


def test_view_acceleration_uses_actual_interval():
    start = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
    points = [
        ObservationPoint(start, view_count=1000),
        ObservationPoint(start + timedelta(minutes=5), view_count=1500),
        ObservationPoint(start + timedelta(minutes=10), view_count=2500),
    ]
    result = calculate_acceleration(points)
    assert result[-1].view_acceleration_per_minute_squared == 20.0


def test_audience_acceleration_can_be_negative():
    start = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
    points = [
        ObservationPoint(start, concurrent_viewers=500),
        ObservationPoint(start + timedelta(minutes=5), concurrent_viewers=750),
        ObservationPoint(start + timedelta(minutes=10), concurrent_viewers=800),
    ]
    result = calculate_acceleration(points)
    assert result[-1].audience_acceleration_per_minute_squared == -40.0


def test_missing_values_are_not_treated_as_zero():
    start = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
    points = [
        ObservationPoint(start, view_count=1000),
        ObservationPoint(start + timedelta(minutes=5), view_count=None),
        ObservationPoint(start + timedelta(minutes=10), view_count=2000),
    ]
    result = calculate_acceleration(points)
    assert result[-1].view_acceleration_per_minute_squared is None


def test_latest_acceleration_empty_input():
    assert latest_acceleration([]) is None
