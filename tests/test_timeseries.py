from metrics.timeseries import compare_metric


def test_compare_metric_calculates_delta_and_percent_change():
    result = compare_metric(100, 125)

    assert result.current == 125.0
    assert result.previous == 100.0
    assert result.delta == 25.0
    assert result.percent_change == 25.0
    assert result.sufficient_data is True


def test_compare_metric_supports_declines():
    result = compare_metric(200, 150)

    assert result.delta == -50.0
    assert result.percent_change == -25.0


def test_compare_metric_does_not_invent_missing_data():
    result = compare_metric(None, 100)

    assert result.current == 100.0
    assert result.previous is None
    assert result.delta is None
    assert result.percent_change is None
    assert result.sufficient_data is False


def test_compare_metric_zero_baseline_has_no_percent_change():
    result = compare_metric(0, 100)

    assert result.delta == 100.0
    assert result.percent_change is None
    assert result.sufficient_data is True
