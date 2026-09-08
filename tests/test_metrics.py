from datetime import datetime, timedelta, timezone

from metrics.engine import ObservationPoint, audience_momentum, average, peak, view_velocity


def test_view_velocity_per_minute():
    start = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)
    previous = ObservationPoint(observed_at=start, view_count=1000)
    current = ObservationPoint(
        observed_at=start + timedelta(minutes=2),
        view_count=1200,
    )
    assert view_velocity(previous, current) == 100.0


def test_audience_momentum_per_minute():
    start = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)
    previous = ObservationPoint(observed_at=start, concurrent_viewers=500)
    current = ObservationPoint(
        observed_at=start + timedelta(minutes=5),
        concurrent_viewers=750,
    )
    assert audience_momentum(previous, current) == 50.0


def test_average_and_peak_ignore_missing_values():
    assert average([10, None, 20]) == 15.0
    assert peak([10, None, 20]) == 20


def test_rates_return_none_when_required_data_is_missing():
    start = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)
    previous = ObservationPoint(observed_at=start, view_count=None)
    current = ObservationPoint(observed_at=start + timedelta(minutes=1), view_count=100)
    assert view_velocity(previous, current) is None
