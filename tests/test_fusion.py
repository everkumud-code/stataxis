from metrics.fusion import build_fused_intelligence
from metrics.stx_index import STXSignals


def test_fusion_uses_index_confidence_for_view():
    result = build_fused_intelligence(["Audience increased", "Momentum strengthened"], STXSignals(audience=80, growth=70, momentum=75))
    assert result.index.score is not None
    assert result.index.confidence == 65
    assert result.view.confidence == result.index.confidence
    assert "positive" in result.view.view


def test_fusion_surfaces_measured_view_velocity():
    result = build_fused_intelligence(["Views are accelerating"], STXSignals(view_velocity=75))
    assert result.index.score == 75
    assert result.index.available_signals == 1
    assert result.view.signals[0].name == "view_velocity"
    assert result.view.signals[0].direction == "positive"
    assert result.view.signals[0].strength == 75
    assert "positive" in result.view.view


def test_fusion_surfaces_mixed_evidence():
    result = build_fused_intelligence(["Growth increased", "Momentum weakened"], STXSignals(growth=80, momentum=20))
    assert result.view.view == "The evidence is mixed; no single directional conclusion is supported."


def test_fusion_handles_no_signals():
    result = build_fused_intelligence([], STXSignals())
    assert result.index.score is None
    assert result.index.confidence == 0
    assert "insufficient" in result.view.view
