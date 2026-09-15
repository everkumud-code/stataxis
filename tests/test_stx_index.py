import pytest

from metrics.stx_index import STXSignals, calculate_stx_index


def test_full_signal_set_produces_weighted_index():
    result = calculate_stx_index(STXSignals(audience=80, growth=70, view_velocity=60, momentum=60, acceleration=50, consistency=90, competitive_position=75, anomaly_event=40))
    assert result.score == pytest.approx(69.0)
    assert result.confidence == 100
    assert result.available_signals == 8


def test_missing_signals_are_not_treated_as_zero():
    result = calculate_stx_index(STXSignals(audience=80, growth=None))
    assert result.score == 80
    assert result.confidence == 25
    assert result.available_signals == 1


def test_no_signals_returns_no_score():
    result = calculate_stx_index(STXSignals())
    assert result.score is None
    assert result.confidence == 0
    assert result.available_signals == 0
    assert result.component_scores == {}


def test_signal_range_is_enforced():
    with pytest.raises(ValueError, match="between 0 and 100"):
        calculate_stx_index(STXSignals(momentum=101))


def test_component_scores_sum_to_final_score():
    result = calculate_stx_index(STXSignals(audience=100, momentum=50, competitive_position=0))
    assert sum(result.component_scores.values()) == pytest.approx(result.score)


def test_view_velocity_is_a_first_class_index_component():
    result = calculate_stx_index(STXSignals(view_velocity=75))
    assert result.score == 75
    assert result.confidence == 10
    assert result.available_signals == 1
    assert result.component_scores["view_velocity"] == pytest.approx(75)
