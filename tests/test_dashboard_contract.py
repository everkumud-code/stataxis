from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_exposes_multi_channel_comparison():
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
    assert "comparison-table-body" in html
    assert "renderMultiChannelComparison" in js
    assert "A vs B vs C" in html
    assert "Average" in html


def test_dashboard_comparison_has_historical_periods_and_demo_preview():
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
    for label in ("3 Weeks", "1 Month", "1 Year"):
        assert label in html
    assert "persisted observation" in js
    assert "No scored channels available for comparison." in js
    assert "Preview" in html
    assert "DEMO DATA" in html
    assert "Request Access" in html
