from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_exposes_current_market_intelligence_contract():
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard" / "media-intelligence.js").read_text(encoding="utf-8")
    assert "MARKET INTELLIGENCE" in html
    assert "market-channel-body" in html
    assert "market-period" in html
    assert "market-scope" in html
    assert "api/v1/markets/report" in js


def test_dashboard_exposes_stx_and_evidence_first_language():
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
    for label in ("3 Weeks", "1 Month", "Quarter"):
        assert label in html
    assert "Missing evidence is not silently scored as zero" in html
    assert "persisted" in js
    assert "No persisted" in js
