from datetime import UTC, datetime, timedelta

import pytest

from metrics.anomaly import detect_anomalies, latest_anomaly


def _points(values: list[float | None]) -> list[tuple[datetime, float | None]]:
    start = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
    return [(start + timedelta(minutes=index), value) for index, value in enumerate(values)]


def test_anomaly_requires_minimum_history():
    result = detect_anomalies(_points([100, 101, 99, 100, 250]), minimum_points=5)
    assert result[-1].is_anomaly is False
    assert result[-1].sufficient_data is False


def test_positive_anomaly_is_detected_against_prior_baseline():
    result = detect_anomalies(_points([100, 101, 99, 100, 102, 250]), minimum_points=5)
    latest = result[-1]
    assert latest.is_anomaly is True
    assert latest.direction == "positive"
    assert latest.baseline == 100


def test_negative_anomaly_is_detected():
    result = detect_anomalies(_points([100, 101, 99, 100, 102, 0]), minimum_points=5)
    latest = result[-1]
    assert latest.is_anomaly is True
    assert latest.direction == "negative"


def test_stable_series_is_not_anomaly():
    result = detect_anomalies(_points([100, 100, 100, 100, 100, 100]), minimum_points=5)
    assert result[-1].is_anomaly is False
    assert result[-1].robust_z_score == 0.0


def test_zero_mad_uses_materiality_floor_for_constant_baseline():
    result = detect_anomalies(_points([100, 100, 100, 100, 100, 106]), minimum_points=5)
    latest = result[-1]
    assert latest.is_anomaly is True
    assert latest.robust_z_score == float("inf")


def test_zero_mad_ignores_tiny_deviation():
    result = detect_anomalies(_points([100, 100, 100, 100, 100, 101]), minimum_points=5)
    assert result[-1].is_anomaly is False
    assert result[-1].robust_z_score == 0.0


def test_missing_values_are_not_zero():
    result = detect_anomalies(
        _points([100, 101, None, 99, 100, None, 98, 250]),
        minimum_points=5,
    )
    assert result[2].sufficient_data is False
    assert result[5].sufficient_data is False
    assert result[5].value is None
    assert result[-1].sufficient_data is True
    assert result[-1].is_anomaly is True


def test_rolling_window_limits_baseline_history():
    result = detect_anomalies(
        _points([100, 100, 100, 100, 100, 200, 200, 201]),
        minimum_points=3,
        window=3,
    )
    assert result[5].is_anomaly is True
    assert result[6].baseline == 100
    assert result[6].is_anomaly is True
    assert result[7].baseline == 200
    assert result[7].is_anomaly is False


def test_invalid_parameters_are_rejected():
    with pytest.raises(ValueError):
        detect_anomalies(_points([1]), minimum_points=0)
    with pytest.raises(ValueError):
        detect_anomalies(_points([1]), z_threshold=0)
    with pytest.raises(ValueError):
        detect_anomalies(_points([1]), minimum_points=5, window=4)


def test_latest_anomaly_empty_input():
    assert latest_anomaly([]) is None
