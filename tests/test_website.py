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
    # the hero is the short form the owner asked for; the tagline stays beside it
    hero = home[home.index('<section class="vx-hero">'):home.index("</section>", home.index('<section class="vx-hero">'))]
    for phrase in ("Digital media market intelligence", "Stand on the right axis.<br>See what the market cannot.", "Precision audience intelligence for India’s media elite.",
                   "▶ Interactive demo", "Platform", "For media buyers", "Stat the View. <em>Axis the Viewpoint.</em>"):
        assert phrase in hero, phrase
    assert len(re.sub(r"<[^>]+>", " ", hero.split('<div class="vx-bar"')[0]).split()) < 40
    # the original sections are all still there, word for word
    for original in ("From evidence to decision intelligence.", "OBSERVE → MEASURE → COMPARE → EXPLAIN", "One intelligence layer. Multiple media surfaces.", "Insights & research become part of the product.",
                     "Intelligence Platform", "Media Buyer Intelligence", "YouTube data, clearly identified.", "Choose where you want to go.", "Admin Console"):
        assert original in home or original.replace("&", "&amp;") in home, original
    assert home.count("Choose where you want to go.") == 1 and home.count("YouTube data, clearly identified.") == 1
    # and the new sections are added
    for addition in ("IFX Score", "Authenticity radar", "tx-matrix", "vx-pulse", "Verified audience programme", "/blog/average-beats-peak", "Eleven questions"):
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
    served = {"/": "index.html", "/login": "login.html", "/admin": "admin.html", "/apply": "apply.html", "/workspace": "workspace.html", "/demo": "workspace.html"}
    for page in [DASH / p for p in PAGES] + POSTS + [DASH / "site.js"]:
        for href in re.findall(r'(?:href|src)=["\'](/[^"\'#?]*)', text(page)):
            target = served.get(href) or (href.lstrip("/") + ".html" if "." not in href.rsplit("/", 1)[-1] else href.lstrip("/"))
            if target and not href.startswith("/api/"):
                assert (DASH / target).is_file(), f"{page.name} links to {href}"


def test_the_blog_is_complete_and_indexed():
    assert len(POSTS) >= 6
    index = text(DASH / "insights.html")
    for p in POSTS:
        html = text(p)
        assert f'/blog/{p.stem}"' in index, p.name
        assert f'<link rel="canonical" href="https://www.stataxis.org/blog/{p.stem}">' in html
        ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1))
        assert ld["@type"] == "Article" and ld["headline"] and ld["datePublished"].startswith("2026-")
        assert len(re.sub(r"<[^>]+>", " ", html).split()) > 250, f"{p.name} is too thin"
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
    for path in ("/", "/ifx", "/blog/data-to-decision", "/platform", "/login", "/apply", "/tech.css", "/tech.js", "/market.js", "/assets/stataxis-logo.svg"):
        status, body = get(path)
        assert status.startswith("200") and body, path
    for path in ("/api/v1/public/pulse", "/api/v1/public/packages"):
        status, body = get(path)
        assert status.startswith("200") and json.loads(body), path
    assert json.loads(get("/api/v1/public/packages")[1])["order"][0] == "sx_free"
    assert get("/api/v1/market/weekly")[0].startswith("401")                 # everything else still needs a login


def test_footer_wordmark_method_stage_and_radar_are_wired():
    site, tech, css, home = text(DASH / "site.js"), text(DASH / "tech.js"), text(DASH / "tech.css"), text(DASH / "index.html")
    assert "vx-wordmark" in site and "vx-wordmark" in tech and "STATAXIS" in tech
    assert 'class="vx-steps vx-acc' in home and 'class="vx-stage' in home and "vx-acc" in tech
    for phrase in ("Prior written permission from StatAxis", "not sourced from, provided by or endorsed by YouTube"):
        assert phrase in site, phrase
    assert ".vx-art .radar svg" in css


def test_the_cursor_drops_letters_and_numbers_from_its_tail_only_for_a_mouse_and_never_for_reduced_motion():
    tech, css = text(DASH / "tech.js"), text(DASH / "tech.css")
    assert "data rain" in tech and "vx-trail" in tech and "pointer:fine" in tech and "reduce" in tech
    assert ".vx-trail{position:fixed" in css and "pointer-events:none" in css


@pytest.mark.parametrize("name", ["platform.html", "solutions.html", "research.html", "stx.html", "insights.html", "ifx.html"])
def test_every_sub_page_has_a_scene_figures_that_count_up_and_a_faq(name):
    html = text(DASH / name)
    assert 'class="vx-scene"' in html and "data-count=" in html and 'class="vx-faq"' in html and "vx-dcol" in html or "vx-paths" in html


def test_the_coverage_plan_is_stated_the_way_the_owner_gave_it_and_the_weights_add_up():
    plat = text(DASH / "platform.html")
    for phrase in ("Jan 2027", "Instagram and Facebook", "Jul 2027", "Connected TV", "subject to the platform"):
        assert phrase in plat, phrase
    stx = text(DASH / "stx.html")
    assert sum(int(x) for x in re.findall(r"<em>(\d+)%</em>", stx)) == 100
    ifx_bars = re.findall(r"<em>(\d+)%</em>", text(DASH / "ifx.html"))
    assert len(ifx_bars) == 15 and sum(int(x) for x in ifx_bars[:3]) == 100 and sum(int(x) for x in ifx_bars[3:]) == 100   # the three pillars, then the twelve parts: each bar adds up to 100


def test_the_scripts_define_the_scenes_the_pages_ask_for():
    tech = text(DASH / "tech.js")
    assert "const SCENES = [" in tech and tech.count("(u, v, t) =>") >= 8
    wanted = {int(n) for name in PAGES for n in re.findall(r'data-scene="(\d+)"', text(DASH / name))}
    assert wanted and max(wanted) < tech.count("(u, v, t) =>")


def test_there_is_no_galaxy_and_no_drawn_stax9_figure_on_the_site():
    tech, css, site = text(DASH / "tech.js"), text(DASH / "tech.css"), text(DASH / "site.js")
    assert "vx-galaxy" not in tech + css
    assert not (DASH / "stax9-explorer.svg").exists()


def test_stax9_is_the_owners_artwork_only_and_the_helper_uses_it():
    import base64
    folder = DASH / "assets" / "stax9"
    assert (folder / "STAX9.png").stat().st_size > 1_000_000 and (folder / "STAX9.svg").stat().st_size > 1_000_000
    header = (folder / "STAX9.png").read_bytes()[:33]
    assert header[:8] == bytes([137, 80, 78, 71, 13, 10, 26, 10]) and header[25] == 6, "the PNG must carry an alpha channel (colour type 6)"
    svg = text(folder / "STAX9.svg")
    assert "<title>STAX9 character</title>" in svg and base64.b64decode(re.search(r"base64,([^\"]+)\"", svg).group(1))[:8] == b"\x89PNG\r\n\x1a\n"
    js, site = text(DASH / "stax9.js"), text(DASH / "site.js")
    assert "stax9-figure.webp" in js and "stax9-head.webp" in js and "stax9.js" in site and "createElementNS" not in js and "<svg" not in js
    assert (folder / "stax9-figure.webp").stat().st_size < 300_000 and (folder / "stax9-head.webp").exists()
    assert "stax9-figure.webp" in text(DASH / "stax9.html") and "stax9-figure.webp" in text(DASH / "media-intelligence.js")
    assert not (DASH / "stax9-explorer.svg").exists()


@pytest.mark.parametrize("name,kind", [("stax9-figure.webp", "image/webp"), ("stax9-head.webp", "image/webp"), ("STAX9.png", "image/png"), ("STAX9.svg", "image/svg+xml")])
def test_the_server_serves_the_stax9_artwork_with_the_right_type(name, kind):
    out = {}
    body = web.application({"REQUEST_METHOD": "GET", "PATH_INFO": "/assets/stax9/" + name, "QUERY_STRING": "", "REMOTE_ADDR": "127.0.0.1"}, lambda status, headers: out.update(status=status, headers=dict(headers)))
    assert out["status"].startswith("200") and out["headers"]["Content-Type"].startswith(kind) and len(b"".join(body)) > 10_000


def test_the_main_menu_has_a_client_login_button_that_leads_to_the_workspace_for_a_signed_in_client():
    site, css = text(DASH / "site.js"), text(DASH / "tech.css")
    assert site.count("data-client-login") >= 3 and 'href="/login"' in site and "Enter StatAxis" in site and "Client login" not in site and "My workspace" in site and '"/workspace"' in site
    assert ".vx-menu a.login" in css


CLEAN = ["/", "/platform", "/solutions", "/ifx", "/stx", "/research", "/insights", "/login", "/apply", "/workspace", "/demo", "/privacy", "/terms", "/stax9", "/blog/average-beats-peak"]


@pytest.mark.parametrize("path", CLEAN)
def test_every_page_opens_at_its_clean_address(path):
    out = {}
    res = web.application({"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "", "REMOTE_ADDR": "127.0.0.1"}, lambda status, headers: out.update(status=status, headers=dict(headers)))
    body = b"".join(res)
    assert out["status"].startswith("200") and out["headers"]["Content-Type"].startswith("text/html") and b"<html" in body[:400].lower(), path


@pytest.mark.parametrize("old,new", [("/login.html", "/login"), ("/platform.html", "/platform"), ("/blog/average-beats-peak.html", "/blog/average-beats-peak"), ("/index.html", "/"), ("/demo.html", "/demo"), ("/workspace.html", "/workspace")])
def test_the_old_html_address_moves_for_good_to_the_clean_one(old, new):
    out = {}
    res = web.application({"REQUEST_METHOD": "GET", "PATH_INFO": old, "QUERY_STRING": "role=media&plan=sx_idea", "REMOTE_ADDR": "127.0.0.1"}, lambda status, headers: out.update(status=status, headers=dict(headers)))
    assert out["status"].startswith("301") and out["headers"]["Location"] == new + "?role=media&plan=sx_idea" and b"".join(res) == b""


@pytest.mark.parametrize("path", ["/nonexistent", "/web", "/dashboard/login", "/blog", "/login/extra", "/../web", "/%2e%2e/web", "/missing.html"])
def test_a_clean_address_that_is_not_a_page_is_not_found_and_cannot_leave_the_site_folder(path):
    out = {}
    res = web.application({"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "", "REMOTE_ADDR": "127.0.0.1"}, lambda status, headers: out.update(status=status, headers=dict(headers)))
    assert out["status"].startswith("404") and b"".join(res) == b"Not found", path


def test_no_internal_link_or_canonical_address_still_ends_in_dot_html():
    for path in [DASH / p for p in PAGES] + POSTS + [DASH / n for n in ("site.js", "tech.js", "stax9.js", "login.html", "apply.html", "workspace.html", "privacy.html", "terms.html")]:
        html = text(path)
        for m in re.finditer(r"""(?:href|src|action)=["']([^"']+)["']|(?:location\.href\s*=|location\.replace\()\s*["']([^"']+)["']""", html):
            target = m.group(1) or m.group(2)
            if target.startswith(("http://", "https://", "mailto:", "#", "data:")) and "stataxis.org" not in target:
                continue
            assert ".html" not in target.split("?")[0].split("#")[0], f"{path.name}: {target}"
        assert not re.search(r"https://www\.stataxis\.org/[^\"'\s]*\.html", html), path.name


def test_channels_are_listed_language_wise_in_pickers_tables_and_the_live_wall():
    ws, market = text(DASH / "workspace.html"), text(DASH / "market.js")
    assert "const LANG_FIRST" in ws and "optsByLanguage" in ws and "groupByLanguage" in ws and "langrow" in ws and "channels.sort(byLanguage)" in ws
    assert market.count("optsByLanguage(") >= 2 and market.count("{group: r => r.language}") >= 3 and "groupByLanguage(d.channels)" in market


def test_the_workspace_menu_is_grouped_by_task_and_lists_every_screen_once_with_a_hint():
    from api import me
    ws = text(DASH / "workspace.html")
    layout = re.search(r"const MENU_LAYOUT = \[(.*?)\n\];", ws, re.S).group(1)
    ids = re.findall(r'"([a-z\-]+)"', re.sub(r'\["[A-Za-z ]+", \[', "[", layout))
    for vid, _label, _feature in me.VIEWS:
        assert ids.count(vid) == 1, vid                                  # every screen a person may be given is in the menu exactly once
    for always in me.ALWAYS:
        assert ids.count(always) == 1, always
    hints = re.search(r"const MENU_HINT = \{(.*?)\n\};", ws, re.S).group(1)
    for vid in ids:
        assert re.search(rf'(?:\b{re.escape(vid)}|"{re.escape(vid)}"): "', hints), f"no hint for {vid}"
    for group in ("Start here", "Watch live", "Know the market", "Plan and report", "Creators and trust", "My account", "People and access"):
        assert f'["{group}"' in layout, group
    assert 'id="navfind"' in ws and "Find a screen" in ws
