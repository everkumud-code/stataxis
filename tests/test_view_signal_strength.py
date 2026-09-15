from metrics.fusion import build_fused_intelligence
from metrics.stx_index import STXSignals


def test_view_preserves_measured_signal_strengths():
    signals = STXSignals(audience=80, growth=70, consistency=100)
    result = build_fused_intelligence(["measured"], signals)

    by_name = {signal.name: signal for signal in result.view.signals}
    assert by_name["audience"].direction == "positive"
    assert by_name["audience"].strength == 80
    assert by_name["growth"].strength == 70
    assert by_name["consistency"].strength == 100


def test_view_treats_midrange_strength_as_neutral():
    result = build_fused_intelligence(["measured"], STXSignals(consistency=50))
    signal = result.view.signals[0]
    assert signal.name == "consistency"
    assert signal.direction == "neutral"
    assert signal.strength == 50
