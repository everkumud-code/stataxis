from datetime import datetime, timedelta, timezone

from metrics.engine import ObservationPoint
from metrics.pipeline import build_intelligence_snapshot
from metrics.timeseries import compare_metric


def test_pipeline_produces_index_view_and_traceable_contributions():
    start = datetime(2026, 9, 14, tzinfo=timezone.utc)
    observations = [
        ObservationPoint(start, view_count=1000, concurrent_viewers=100),
        ObservationPoint(start + timedelta(minutes=1), view_count=1120, concurrent_viewers=130),
        ObservationPoint(start + timedelta(minutes=2), view_count=1280, concurrent_viewers=170),
    ]

    result = build_intelligence_snapshot(
        data=["Views increased from 1,000 to 1,280"],
        observations=observations,
        audience_change=compare_metric(1000, 1280),
        growth_change=compare_metric(100, 128),
    )

    assert result.intelligence.index.score is not None
    assert result.intelligence.index.available_signals >= 3
    assert result.intelligence.view.confidence == result.intelligence.index.confidence
    assert sum(item.weighted_contribution for item in result.contributions) == result.intelligence.index.score


def test_pipeline_preserves_missing_time_series_signals():
    result = build_intelligence_snapshot(
        data=[],
        observations=[ObservationPoint(datetime(2026, 9, 14, tzinfo=timezone.utc), view_count=100)],
        audience_change=compare_metric(None, 100),
        growth_change=compare_metric(None, 10),
    )

    assert result.intelligence.index.score is None
    assert result.intelligence.index.confidence == 0
    assert result.contributions == ()
