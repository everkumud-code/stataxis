from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_exposes_channel_comparison_controls():
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
    for marker in ("market-channel-body", "channel-compare-grid", "market-interval", "market-show", "market-compare"):
        assert marker in html
    assert "A vs B vs C vs Average" in html
    assert "Current + Peak + Average" in html
    assert "Individual Channel Data" in html
    assert "renderMultiChannelComparison" in js


def test_dashboard_has_public_demo_and_historical_intelligence():
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
    for label in ("3 Weeks", "1 Month", "1 Year"):
        assert label in html
    for marker in ("DEMO DATA", "PUBLIC PREVIEW", "Request Access", "How to Use", "Download Sample Report"):
        assert marker in html
    assert "persisted observation" in js
    assert "No scored channels available for comparison." in js
