from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"


def test_dashboard_exposes_current_market_intelligence_contract():
    html = (DASHBOARD / "media-intelligence.html").read_text(encoding="utf-8")
    js = (DASHBOARD / "media-intelligence.js").read_text(encoding="utf-8")
    assert "MARKET & COMPETITION" in html
    assert "market-channel-body" in js
    assert "market-period" in js
    assert "market-scope" in js
    assert "api/v1/markets/report" in js


def test_dashboard_exposes_stx_and_evidence_first_language():
    js = (DASHBOARD / "app.js").read_text(encoding="utf-8")
    assert "3 Weeks" in js
    assert "1 Month" in js
    assert "persisted" in js
    assert "No persisted" in js
