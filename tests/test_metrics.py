from datetime import UTC, datetime, timedelta

from metrics.engine import (
    ObservationPoint,
    audience_momentum,
    average,
    engagement_rate,
    peak,
    view_velocity,
)


def test_view_velocity_per_minute():
    start = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
    previous = ObservationPoint(observed_at=start, view_count=1000)
    current = ObservationPoint(
        observed_at=start + timedelta(minutes=2),
        view_count=1200,
    )
    assert view_velocity(previous, current) == 100.0


def test_audience_momentum_per_minute():
    start = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
    previous = ObservationPoint(observed_at=start, concurrent_viewers=500)
    current = ObservationPoint(
        observed_at=start + timedelta(minutes=5),
        concurrent_viewers=750,
    )
    assert audience_momentum(previous, current) == 50.0


def test_engagement_rate_per_minute():
    start = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
    previous = ObservationPoint(
        observed_at=start,
        like_count=10,
        comment_count=2,
    )
    current = ObservationPoint(
        observed_at=start + timedelta(minutes=2),
        like_count=16,
        comment_count=5,
    )
    assert engagement_rate(previous, current) == 4.5


def test_rates_return_none_for_non_positive_elapsed_time():
    start = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
    previous = ObservationPoint(
        observed_at=start,
        view_count=1000,
        concurrent_viewers=500,
        like_count=10,
        comment_count=2,
    )
    identical = ObservationPoint(
        observed_at=start,
        view_count=1200,
        concurrent_viewers=750,
        like_count=16,
        comment_count=5,
    )
    reversed_current = ObservationPoint(
        observed_at=start - timedelta(minutes=2),
        view_count=1200,
        concurrent_viewers=750,
        like_count=16,
        comment_count=5,
    )

    for current in (identical, reversed_current):
        assert view_velocity(previous, current) is None
        assert audience_momentum(previous, current) is None
        assert engagement_rate(previous, current) is None


def test_average_and_peak_ignore_missing_values():
    assert average([10, None, 20]) == 15.0
    assert peak([10, None, 20]) == 20


def test_rates_return_none_when_required_data_is_missing():
    start = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
    previous = ObservationPoint(observed_at=start, view_count=None)
    current = ObservationPoint(observed_at=start + timedelta(minutes=1), view_count=100)
    assert view_velocity(previous, current) is None
