from metrics.view import Signal, build_stat_axis_view


def test_view_separates_data_analysis_and_viewpoint():
    result = build_stat_axis_view(
        ["Audience increased 18%"],
        [Signal("growth", "positive")],
        90,
    )
    assert result.data == ("Audience increased 18%",)
    assert result.analysis == ("Available signals are directionally positive (1 positive).",)
    assert result.view == "The available evidence supports a positive directional signal."
    assert result.confidence == 90


def test_view_does_not_force_a_conclusion_when_signals_conflict():
    result = build_stat_axis_view(
        ["Audience increased", "Momentum declined"],
        [Signal("growth", "positive"), Signal("momentum", "negative")],
        100,
    )
    assert "mixed" in result.analysis[0]
    assert "mixed" in result.view


def test_view_reports_insufficient_directional_evidence():
    result = build_stat_axis_view([], [Signal("audience", "neutral")], 0)
    assert "insufficient" in result.view


def test_view_rejects_invalid_confidence():
    try:
        build_stat_axis_view([], [], 101)
    except ValueError as exc:
        assert "confidence" in str(exc)
    else:
        raise AssertionError("expected ValueError")
