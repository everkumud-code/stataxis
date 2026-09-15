from datetime import datetime, timedelta, timezone

from metrics.engine import ObservationPoint
from metrics.signal_factory import build_stx_signals
from metrics.timeseries import compare_metric
from metrics.velocity import VelocityPoint


def test_engagement_uses_measured_likes_and_comments():
    now = datetime.now(timezone.utc)
    observations = [
        ObservationPoint(now, like_count=100, comment_count=20),
        ObservationPoint(now + timedelta(minutes=2), like_count=130, comment_count=30),
    ]
    result = build_stx_signals(
        compare_metric(1000, 1200),
        compare_metric(1000, 1200),
        VelocityPoint(now, 100.0, None),
        observations=observations,
    )
    assert result.engagement == 52.0


def test_engagement_stays_missing_when_interaction_data_is_incomplete():
    now = datetime.now(timezone.utc)
    observations = [
        ObservationPoint(now, like_count=100),
        ObservationPoint(now + timedelta(minutes=1), like_count=120),
    ]
    result = build_stx_signals(
        compare_metric(100, 110),
        compare_metric(100, 110),
        VelocityPoint(now, 10.0, None),
        observations=observations,
    )
    assert result.engagement is None
