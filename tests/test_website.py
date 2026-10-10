"""The public website: every page loads the shared look, every internal link lands on a file, the blog is complete, the logo is the original and the YouTube disclosure is still on the home page."""
import hashlib
import json
import re
from pathlib import Path

import pytest

import web

DASH = Path(__file__).resolve().parent.parent / "dashboard"
ORIGINAL_LOGO_SHA256 = "907a8ab8a1c9f339329ef403b86062815f82089cc2905353d716425213a316c6"
PAGES = ["index.html", "platform.html", "solutions.html", "ifx.html", "stx.html", "research.html", "insights.html"]
POSTS = sorted((DASH / "blog").glob("*.html"))


def text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_the_logo_is_the_original_one():
    assert hashlib.sha256((DASH / "assets" / "stataxis-logo.svg").read_bytes()).hexdigest() == ORIGINAL_LOGO_SHA256
    assert "assets/stataxis-logo.svg" in text(DASH / "site.js")


@pytest.mark.parametrize("name", PAGES + [f"blog/{p.name}" for p in POSTS])
def test_each_public_page_has_the_look_a_title_a_description_and_the_shared_chrome(name):
    html = text(DASH / name)
    assert "tech.css" in html and "site.js" in html and "tech.js" in html and 'id="nav"' in html and 'id="footer"' in html
    assert re.search(r"<title>[^<]{12,}</title>", html) and re.search(r'<meta name="description" content="[^"]{40,}"', html)
    assert html.count("<h1") == 1


def test_the_home_page_keeps_the_original_content_and_adds_to_it():
    home = text(DASH / "index.html")
    assert "YouTube is a trademark of Google LLC" in home and "not endorsed by YouTube or Google" in home and "youtube.com/t/terms" in home
    # the original hero text is untouched and the tagline sits beside it
    for original in ("DIGITAL MEDIA MARKET INTELLIGENCE & DATA SERVICES", "See the market.<br>Understand the signal.<br>Make better decisions.",
                     "StatAxis brings measurement, market intelligence, research and custom data services together for businesses, media buyers, agencies, publishers and research teams.",
                     "Explore Interactive Demo", "Explore Platform", "For Corporates & Media Buyers", "Stat the View. <em>Axis the Viewpoint.</em>"):
        assert original in home or original.replace("&", "&amp;") in home, original
    # the original sections are all still there, word for word
    for original in ("From evidence to decision intelligence.", "OBSERVE → MEASURE → COMPARE → EXPLAIN", "One intelligence layer. Multiple media surfaces.", "Insights & research become part of the product.",
                     "Intelligence Platform", "Media Buyer Intelligence", "YouTube data, clearly identified.", "Choose where you want to go.", "Admin Console"):
        assert original in home or original.replace("&", "&amp;") in home, original
    assert home.count("Choose where you want to go.") == 1 and home.count("YouTube data, clearly identified.") == 1
    # and the new sections are added
    for addition in ("IFX Score", "Authenticity radar", "tx-matrix", "vx-pulse", "Verified audience programme", "/blog/average-beats-peak.html", "Eleven questions"):
        assert addition in home, addition


def test_the_other_original_pages_keep_their_words():
    expect = {"platform.html": ("One place to understand the digital media market.", "DATA → ANALYSIS → STATAXIS VIEW", "Data organised around the questions users actually ask."),
              "solutions.html": ("Data that supports the decision.", "Built for teams that need evidence.", "Channel benchmarking", "Industry reports"),
              "research.html": ("Digital signals, market evidence and human answers.", "Perspective matters.", "IIM Calcutta"),
              "stx.html": ("STX Index™ turns multiple signals into one qualified view.", "Seven weighted components.", "Missing is not zero"),
              "insights.html": ("The market, explained with evidence.", "How to read a digital media market", "From digital video to social and CTV")}
    for name, phrases in expect.items():
        html = text(DASH / name)
        for ph in phrases:
            assert ph in html, f"{name}: {ph}"


def test_every_internal_link_and_script_lands_on_a_file():
    served = {"/": "index.html", "/login": "login.html", "/admin": "admin.html", "/apply": "apply.html", "/workspace": "workspace.html"}
    for page in [DASH / p for p in PAGES] + POSTS + [DASH / "site.js"]:
        for href in re.findall(r'(?:href|src)=["\'](/[^"\'#?]*)', text(page)):
            target = served.get(href) or href.lstrip("/")
            if target and not href.startswith("/api/"):
                assert (DASH / target).is_file(), f"{page.name} links to {href}"


def test_the_blog_is_complete_and_indexed():
    assert len(POSTS) >= 6
    index = text(DASH / "insights.html")
    for p in POSTS:
        html = text(p)
        assert f"/blog/{p.name}" in index, p.name
        assert f'<link rel="canonical" href="https://www.stataxis.org/blog/{p.name}">' in html
        ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1))
        assert ld["@type"] == "Article" and ld["headline"] and ld["datePublished"].startswith("2026-")
        assert len(re.sub(r"<[^>]+>", " ", html).split()) > 500, f"{p.name} is too thin"
    assert "vx-prose" in text(POSTS[0])


def test_the_site_never_claims_what_it_cannot_measure():
    allowed_negations = ("not ", "never", "cannot", "no ")
    for p in [DASH / n for n in PAGES] + POSTS:
        html = text(p).lower()
        for banned in ("guaranteed", "100% accurate", "tv ratings", "real-time tv"):
            for m in re.finditer(re.escape(banned), html):
                context = html[max(0, m.start() - 40):m.start()]
                assert any(n in context for n in allowed_negations), f"{p.name}: '{banned}' without a negation"


def test_the_web_app_serves_the_new_pages_and_the_public_endpoints_without_login():
    def get(path):
        out = {}
        res = web.application({"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "", "REMOTE_ADDR": "127.0.0.1"}, lambda status, headers: out.update(status=status, headers=dict(headers)))
        return out["status"], b"".join(res)
    for path in ("/", "/ifx.html", "/blog/data-to-decision.html", "/tech.css", "/tech.js", "/market.js", "/assets/stataxis-logo.svg"):
        status, body = get(path)
        assert status.startswith("200") and body, path
    for path in ("/api/v1/public/pulse", "/api/v1/public/packages"):
        status, body = get(path)
        assert status.startswith("200") and json.loads(body), path
    assert json.loads(get("/api/v1/public/packages")[1])["order"][0] == "sx_free"
    assert get("/api/v1/market/weekly")[0].startswith("401")                 # everything else still needs a login
