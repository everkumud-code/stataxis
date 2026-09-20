import pytest

from metrics.stx_index import STXSignals, calculate_stx_index


def test_full_signal_set_uses_published_seven_component_weights():
    result = calculate_stx_index(
        STXSignals(
            audience=80,
            growth=70,
            view_velocity=60,
            momentum=60,
            acceleration=50,
            consistency=90,
            competitive_position=75,
            anomaly_event=40,
        )
    )
    assert result.score == pytest.approx(70.5)
    assert result.confidence == 100
    assert result.available_signals == 7
    assert "view_velocity" not in result.component_scores


def test_missing_signals_are_not_treated_as_zero():
    result = calculate_stx_index(STXSignals(audience=80, growth=None))
    assert result.score == 80
    assert result.confidence == 30
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


def test_view_velocity_remains_a_supporting_signal_not_index_component():
    result = calculate_stx_index(STXSignals(view_velocity=75))
    assert result.score is None
    assert result.confidence == 0
    assert result.available_signals == 0
    assert result.component_scores == {}


def test_stx_display_confidence_adjusts_without_changing_raw_score():
    from metrics.stx_index import stx_display

    assert stx_display(100, 10) == {
        "display_score": 55.0,
        "preliminary": True,
        "display_method": "50 + (score - 50) * confidence / 100",
    }
    assert stx_display(100, 100)["display_score"] == 100.0
    assert stx_display(80, 50)["display_score"] == 65.0
    assert stx_display(80, 50)["preliminary"] is False
    assert stx_display(80, 49.9)["preliminary"] is True


def test_stx_display_handles_missing_score_and_clamps_confidence():
    from metrics.stx_index import stx_display

    assert stx_display(None, 80) == {
        "display_score": None,
        "preliminary": True,
        "display_method": "50 + (score - 50) * confidence / 100",
    }
    assert stx_display(100, 150)["display_score"] == 100.0
    assert stx_display(100, -20)["display_score"] == 50.0
