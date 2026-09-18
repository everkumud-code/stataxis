from api.presentation import intelligence_payload
from metrics.fusion import build_fused_intelligence
from metrics.stx_index import STXSignals


def test_intelligence_payload_is_dashboard_ready():
    result = build_fused_intelligence(["Audience increased 18%"], STXSignals(audience=90, growth=70, momentum=65))
    payload = intelligence_payload(result)
    assert payload["stx_index"]["score"] is not None
    assert payload["stx_index"]["confidence"] == 65
    assert payload["data"] == ["Audience increased 18%"]
    assert payload["analysis"]
    assert payload["view"]
    assert payload["signal_contributions"][0]["name"] == "audience"


def test_empty_intelligence_remains_explicit():
    payload = intelligence_payload(build_fused_intelligence([], STXSignals()))
    assert payload["stx_index"]["score"] is None
    assert payload["stx_index"]["confidence"] == 0
    assert payload["signal_contributions"] == []
