"""The user manual (dashboard/manual.html) must say what the code does: the weights, the worked examples, the collection intervals, the Shorts rule and the primary threshold are checked against the code, so the manual cannot drift from it.
It must not name other products, it must end with the FAQ, and it must be linked from the site."""
import re
from pathlib import Path

from api.methodology import methodology
from collector.classification import LEGACY_SHORT_MAX_SECONDS, SHORT_MAX_SECONDS, SHORTS_EXTENDED_FROM
from metrics.feeds import DEFAULT_MIN_PRIMARY_HOURS
from metrics.stx_index import WEIGHTS

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "dashboard" / "manual.html").read_text(encoding="utf-8")


def text():
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", PAGE))


def test_the_sections_are_all_there_and_the_faq_is_last():
    ids = re.findall(r'<h2 id="([a-z]+)"', PAGE)
    assert ids == ["what", "start", "screens", "source", "figures", "stx", "ifx", "method", "read", "use", "reports", "different", "privacy", "faq"]
    assert PAGE.rindex("<h2") > PAGE.rindex('id="privacy"') and PAGE.rindex("<h2") == PAGE.index('<h2 id="faq"')   # the FAQ is the last section
    assert PAGE.count("<details class=\"faq\">") >= 20
    assert PAGE.index('id="faq"') > PAGE.index('id="different"')
    for anchor in ids:
        assert f'href="#{anchor}"' in PAGE            # every section is in the contents


def test_no_other_product_is_named():
    low = text().lower()
    for name in ("ratingology", "data being", "databeing", "scaleup", "barc", "comscore"):
        assert name not in low


def test_the_fallback_weights_in_the_page_are_the_weights_in_the_code():
    block = re.search(r"const STX_FALLBACK = \{([^}]*)\}", PAGE).group(1)
    page = {k: float(v) for k, v in re.findall(r"(\w+):\s*([0-9.]+)", block)}
    assert page == WEIGHTS and abs(sum(page.values()) - 1.0) < 1e-9


def test_the_worked_example_is_worked_out_the_way_the_code_works_it_out():
    signals = {"audience": 60, "growth": 55, "momentum": 48, "acceleration": 50, "consistency": 70, "competitive_position": 100 / 4, "anomaly_event": 52}

    def shown(have):
        wsum = sum(WEIGHTS[k] for k in have)
        stx = sum(signals[k] * WEIGHTS[k] for k in have) / wsum
        conf = wsum * 100
        return round(stx, 1), round(conf), round(50 + (stx - 50) * conf / 100, 1)
    assert shown(list(signals)) == (53.3, 100, 53.3)
    assert shown([k for k in signals if k not in ("acceleration", "anomaly_event")]) == (53.8, 85, 53.2)
    t = text()
    assert "= 53.3" in t and "Shown 53.3" in t and "STX = 45.7 ÷ 0.85 = 53.8" in t and "Shown = 50 + (53.8 − 50) × 0.85 = 53.2" in t


def test_the_ifx_pillars_and_parts_are_the_ones_in_the_code():
    m = methodology()["ifx"]
    assert m["pillar_weights"] == {"impact": 0.35, "followership": 0.35, "exposure": 0.3} and len(m["parts"]) == 16
    assert abs(sum(p["weight"] for p in m["parts"]) - 1.0) < 1e-9
    t = text()
    assert "sixteen" in t and "Impact 35% · Followership 35% · eXposure 30%" in t
    for name in ("best upload against audience size", "reaching beyond own subscribers", "momentum (newer uploads against older)", "early pull of new uploads"):
        assert name in t.lower()


def test_the_collection_intervals_the_shorts_rule_and_the_primary_threshold_match_the_code():
    m = methodology()
    assert "75 seconds" in m["collection"]["live_reading"] and "107 minutes" in m["collection"]["uploads"] and "30 minutes" in m["collection"]["uploads"]
    t = text()
    assert "about every 75 seconds" in t and "about every 107 minutes" in t and "about every 30 minutes" in t
    assert f"A video of {SHORT_MAX_SECONDS} seconds or less ({LEGACY_SHORT_MAX_SECONDS} seconds or less if uploaded before {SHORTS_EXTENDED_FROM:%d %B %Y})" in t
    assert DEFAULT_MIN_PRIMARY_HOURS == 30 * 24 and "at least the primary threshold (30 days)" in t and "live for at least 30 days" in t
    assert "180 seconds" in t and "06:00 IST" in t and "within 20%" in t


def test_the_manual_is_in_the_main_menu_the_footer_and_the_workspace_header():
    site = (ROOT / "dashboard" / "site.js").read_text(encoding="utf-8")
    assert site.count('["/manual", "User manual"]') == 2           # the main menu (and its phone drawer, built from it) and the footer
    assert re.search(r'MENU = \[.*\["/manual", "User manual"\]\];', site)
    assert 'id="manuallink" href="/manual"' in (ROOT / "dashboard" / "workspace.html").read_text(encoding="utf-8")
    assert "/manual" in (ROOT / "api" / "services_cms.py").read_text(encoding="utf-8")
    assert 'href="/manual"' in (ROOT / "dashboard" / "guide.html").read_text(encoding="utf-8")
    assert 'href="/manual"' in (ROOT / "dashboard" / "methodology.html").read_text(encoding="utf-8")


def test_the_manual_makes_no_claim_about_other_products_and_states_its_limits():
    t = text().lower()
    assert "not television ratings" in t and "not proof" in t and "never as zero" in t
    assert "roadmap" in t and "nothing is claimed before it exists" in t
