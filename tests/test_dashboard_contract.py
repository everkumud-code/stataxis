from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_exposes_persisted_multi_channel_comparison():
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
    assert "comparison-table-body" in html
    assert "/api/v1/channels/compare?ids=" in js
    assert "renderMultiChannelComparison" in js


def test_dashboard_comparison_has_historical_periods_and_no_demo_copy():
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
    for label in ("3 Weeks", "1 Month", "1 Year"):
        assert label in html
    assert "persisted STX intelligence only" in js
    assert "No scored channels available for comparison." in js
