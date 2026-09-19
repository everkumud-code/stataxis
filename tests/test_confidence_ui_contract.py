from pathlib import Path
from datetime import datetime

from metrics.market_stx import build_market_stx
from metrics.stx_index import STXSignals, calculate_stx_index

DASHBOARD = Path(__file__).parents[1] / "dashboard"


def _assert_confidence_0_to_100(value):
    assert isinstance(value, (int, float))
    assert 0 <= value <= 100


def test_ui_confidence_contract_uses_backend_0_to_100_values():
    index = calculate_stx_index(STXSignals(audience=80, growth=70))
    _assert_confidence_0_to_100(index.confidence)

    rows = [
        {"channel_id": 1, "channel_name": "Test", "observed_at": datetime(2026, 9, 16, 10, 0), "view_count": 100, "concurrent_viewers": 20, "like_count": 1, "comment_count": 1},
        {"channel_id": 1, "channel_name": "Test", "observed_at": __import__("datetime").datetime(2026, 9, 16, 10, 5), "view_count": 120, "concurrent_viewers": 25, "like_count": 2, "comment_count": 1},
    ]
    market = build_market_stx(rows, [], channel_ids=[1])[1]
    _assert_confidence_0_to_100(market["confidence"])

    sources = [
        (DASHBOARD / "app.js").read_text(),
        (DASHBOARD / "evaluate.js").read_text(),
        (DASHBOARD / "live.js").read_text(),
        (DASHBOARD / "media-intelligence.js").read_text(),
    ]
    assert all("confidence * 100" not in source for source in sources)
    assert all("confidence)*100" not in source for source in sources)
