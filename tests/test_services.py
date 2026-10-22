"""The Services section of the website: the starter services, writing and publishing them, the history, the pages the server writes (and what a search engine reads in them), the sitemap, robots and llms.txt,
moved and removed addresses, the editing routes and who may use them. Invented data in a scratch database."""
import io
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import services_cms, services_seed
from api.auth import AuthIdentity, hash_password, issue_token
from api.services_http import cms_application, site_response
from collector.storage import AppSetting, Base, Service, User

DASH = Path(__file__).resolve().parent.parent / "dashboard"


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    services_cms.invalidate()


def make_session():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return Session(engine), engine


def seeded():
    s, engine = make_session()
    services_cms.ensure_seed(s)
    return s, engine


def good(**over):
    base = {"name": "Brand Pulse", "tagline": "A short line.", "intro": "First paragraph.\n\nSecond paragraph.", "deliverables": "One thing\nAnother thing", "audience": "Brands", "limits": "Not this"}
    return {**base, **over}


# ------------------------------------------------------------------------------------------------------------------------------ the starter services
def test_the_starter_services_are_written_once_published_and_editable():
    s, _ = seeded()
    rows = services_cms.list_services(s)
    assert len(rows) == 11 and all(r["status"] == "published" for r in rows) and [r["sort_order"] for r in rows] == list(range(1, 12))
    services_cms.ensure_seed(s)
    assert s.query(Service).count() == 11                                     # a second start adds nothing
    services_cms.delete_service(s, "owner", rows[0]["id"])
    services_cms.ensure_seed(s)
    assert s.query(Service).count() == 10                                     # a deleted starter does not come back by itself
    assert services_cms.restore_starters(s, "owner")["added"] == [rows[0]["slug"]]
    assert s.query(Service).count() == 11
    current = next(r for r in services_cms.list_services(s) if r["id"] == rows[1]["id"])
    edited = services_cms.save_service(s, "owner", {**current, "tagline": "My own words."}, rows[1]["id"])
    assert services_cms.restore_starters(s, "owner")["added"] == [] and services_cms.serialize(s.get(Service, edited["id"]))["tagline"] == "My own words."   # an edited starter is never overwritten


def test_every_starter_is_complete_distinct_honest_and_good_for_search():
    items = services_seed.SERVICES
    assert len({i["slug"] for i in items}) == 11 and len({i["name"] for i in items}) == 11 and len({i["seo_title"] for i in items}) == 11 and len({i["seo_description"] for i in items}) == 11
    s, _ = seeded()
    published = services_cms.list_services(s)
    for d in published:
        assert 4 <= len(d["steps"]) <= 4 and len(d["faqs"]) >= 3 and len(d["deliverables"]) >= 5 and len(d["limits"]) >= 3 and 2 <= len(d["related"]) <= 3, d["slug"]
        assert all(r in {p["slug"] for p in published} for r in d["related"]), d["slug"]
        assert not [c for c in services_cms.seo_report(d, published) if c["level"] == "bad"], d["slug"]
        assert 30 <= len(d["seo_title"]) <= 60 and 70 <= len(d["seo_description"]) <= 160, d["slug"]
        text = json.dumps(d).lower()
        for banned in ("guaranteed accuracy", "100% accurate", "tv ratings", "real-time tv"):
            assert banned not in text, (d["slug"], banned)
        assert "instagram" not in text.replace("instagram and facebook are planned for january 2027", "") or "planned" in text, d["slug"]   # no platform is promised before its date
    assert "January 2027" in services_seed.COVERAGE_NOTE and "July 2027" in services_seed.COVERAGE_NOTE


# ------------------------------------------------------------------------------------------------------------------------------ writing a service
def test_what_a_person_must_fix_is_said_plainly():
    s, _ = seeded()
    with pytest.raises(ValueError, match="name cannot be empty"):
        services_cms.save_service(s, "o", good(name=" "))
    with pytest.raises(ValueError, match="already used"):
        services_cms.save_service(s, "o", good(slug="custom-research"))
    with pytest.raises(ValueError, match="at most 8"):
        services_cms.save_service(s, "o", good(steps=[{"title": f"s{i}", "text": "x"} for i in range(9)]))
    with pytest.raises(ValueError, match="canonical"):
        services_cms.save_service(s, "o", good(canonical_url="https://example.com/x"))
    with pytest.raises(ValueError, match="canonical"):
        services_cms.save_service(s, "o", good(canonical_url="http://www.stataxis.org/services/x"))
    with pytest.raises(ValueError, match="to publish"):
        services_cms.save_service(s, "o", {"name": "Empty one", "status": "published"})
    assert services_cms.save_service(s, "o", {"name": "Empty one"})["status"] == "draft"            # a draft may be unfinished
    with pytest.raises(ValueError, match="too long"):
        services_cms.save_service(s, "o", good(tagline="x" * 401))


def test_a_service_is_saved_published_ordered_and_every_change_is_kept():
    s, _ = seeded()
    new = services_cms.save_service(s, "ever@x.in", good(related=["custom-research", "no-such", "brand-pulse"]))
    assert new["slug"] == "brand-pulse" and new["status"] == "draft" and new["related"] == ["custom-research"] and new["sort_order"] == 12 and new["nav_label"] == "Brand Pulse"
    assert "brand-pulse" not in [p["slug"] for p in services_cms.list_services(s, published_only=True)]
    services_cms.set_status(s, "ever@x.in", new["id"], "published")
    assert "brand-pulse" in [p["slug"] for p in services_cms.list_services(s, published_only=True)]
    services_cms.save_service(s, "ever@x.in", good(tagline="Changed."), new["id"])
    actions = [r["action"] for r in services_cms.revisions(s, new["id"])]
    assert actions[0] in {"update"} and "publish" in actions and "create" in actions
    ids = [r["id"] for r in services_cms.list_services(s)]
    order = services_cms.reorder(s, "o", [new["id"]] + ids[:3])
    assert order[0]["id"] == new["id"] and [r["sort_order"] for r in order] == list(range(1, 13)) and len(order) == 12   # the ones not named keep their relative order
    services_cms.set_status(s, "o", new["id"], "draft")
    assert services_cms.revisions(s, new["id"])[0]["action"] == "unpublish"


def test_an_earlier_version_can_be_put_back_as_a_draft_and_a_deleted_service_can_return():
    s, _ = seeded()
    a = services_cms.save_service(s, "o", good(tagline="First line."))
    services_cms.save_service(s, "o", good(tagline="Second line."), a["id"])
    first = [r for r in services_cms.revisions(s, a["id"]) if r["action"] == "create"][0]
    back = services_cms.restore(s, "o", first["id"])
    assert back["tagline"] == "First line." and back["status"] == "draft" and back["id"] == a["id"]
    services_cms.delete_service(s, "o", a["id"])
    assert s.get(Service, a["id"]) is None and services_cms.deleted_revisions(s)[0]["slug"] == "brand-pulse"
    gone = [r for r in s.query(__import__("collector.storage", fromlist=["ServiceRevision"]).ServiceRevision).filter_by(action="delete")][0]
    again = services_cms.restore(s, "o", gone.id)
    assert again["slug"] == "brand-pulse" and again["status"] == "draft" and services_cms.deleted_revisions(s) == []


def test_the_services_page_settings_are_editable_and_fall_back_to_the_defaults():
    s, _ = seeded()
    assert services_cms.page_settings(s)["heading"] == services_seed.PAGE_DEFAULTS["heading"]
    saved = services_cms.save_page_settings(s, "o", {"heading": "Our services", "lead": "", "kicker": "", "seo_title": "T", "seo_description": ""})
    assert saved["heading"] == "Our services" and saved["lead"] == services_seed.PAGE_DEFAULTS["lead"]
    assert services_cms.page_settings(s)["heading"] == "Our services"


# ------------------------------------------------------------------------------------------------------------------------------ what a search engine reads
def page_of(s, slug):
    published = services_cms.list_services(s, published_only=True)
    return services_cms.render_service(next(p for p in published if p["slug"] == slug), published)


def ld_blocks(html):
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


def test_a_service_page_carries_everything_a_search_engine_looks_for():
    s, _ = seeded()
    html = page_of(s, "custom-research")
    assert html.count("<h1") == 1 and '<html lang="en-IN">' in html and html.count("<title>") == 1
    assert '<link rel="canonical" href="https://www.stataxis.org/services/custom-research">' in html
    assert 'name="robots" content="index,follow' in html and 'property="og:title"' in html and 'property="og:url" content="https://www.stataxis.org/services/custom-research"' in html and 'name="twitter:card"' in html
    assert re.search(r'<meta name="description" content="[^"]{70,160}"', html)
    kinds = {b["@type"] for b in ld_blocks(html)}
    assert kinds == {"Service", "BreadcrumbList", "FAQPage"}
    service = next(b for b in ld_blocks(html) if b["@type"] == "Service")
    assert service["provider"]["name"] == "StatAxis" and service["url"].endswith("/services/custom-research") and service["hasOfferCatalog"]["itemListElement"]
    assert 'href="/services"' in html and 'href="/services/' in html and 'src="/site.js"' in html and 'href="/site.css"' in html       # breadcrumb, related links, shared look with absolute paths
    assert "<details>" in html and "January 2027" in html
    assert len(re.sub(r"<[^>]+>", " ", html).split()) > 300


def test_a_page_is_safe_whatever_is_typed_into_it():
    s, _ = seeded()
    services_cms.save_service(s, "o", good(name='<script>alert(1)</script> & "co"', slug="xss-check", tagline="<img src=x onerror=alert(1)>", intro="</script><script>alert(2)</script>", status="published",
                                           faqs=[{"q": "<b>q</b>", "a": "</script><i>a</i>"}], seo_title='"><script>1</script>'))
    html = page_of(s, "xss-check")
    assert "<script>alert" not in html and "<img src=x" not in html and "</script><script>" not in html and "<b>q</b>" not in html
    for block in ld_blocks(html):                                                                                    # the structured data is still valid JSON after the escaping
        assert block["@context"] == "https://schema.org"


def test_noindex_canonical_and_preview_are_respected():
    s, _ = seeded()
    services_cms.save_service(s, "o", good(slug="hidden-one", status="published", noindex=True, canonical_url="https://www.stataxis.org/services/custom-research"))
    html = page_of(s, "hidden-one")
    assert 'content="noindex,follow"' in html and '<link rel="canonical" href="https://www.stataxis.org/services/custom-research">' in html
    sitemap = services_cms.sitemap_xml(s)
    assert "hidden-one" not in sitemap and "hidden-one" not in services_cms.llms_txt(s)
    d = services_cms.list_services(s, published_only=True)[0]
    assert 'content="noindex,follow"' in services_cms.render_service(d, [d], preview=True)                       # a preview is never indexed


def test_the_services_index_page_lists_published_services_with_a_collection_schema():
    s, _ = seeded()
    html = services_cms.render_index(services_cms.list_services(s, published_only=True), services_cms.page_settings(s))
    assert html.count("<h1") == 1 and html.count('href="/services/') == 11 and '<link rel="canonical" href="https://www.stataxis.org/services">' in html
    coll = next(b for b in ld_blocks(html) if b["@type"] == "CollectionPage")
    assert len(coll["mainEntity"]["itemListElement"]) == 11 and any(b["@type"] == "Organization" for b in ld_blocks(html))


def test_sitemap_robots_and_llms_list_what_is_public_and_hide_the_rest():
    s, _ = seeded()
    services_cms.save_service(s, "o", good(slug="draft-one"))
    sm = services_cms.sitemap_xml(s)
    assert sm.startswith("<?xml") and sm.count("<loc>https://www.stataxis.org/services/") == 11 and "draft-one" not in sm and "<loc>https://www.stataxis.org/services</loc>" in sm
    assert "<loc>https://www.stataxis.org/</loc>" in sm and "<loc>https://www.stataxis.org/platform</loc>" in sm and "/blog/ifx-score-explained" in sm and "/workspace" not in sm and "/login" not in sm
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", m) for m in re.findall(r"<lastmod>([^<]+)</lastmod>", sm))
    robots = services_cms.robots_txt()
    assert "Allow: /" in robots and "Disallow: /workspace" in robots and "Disallow: /api/" in robots and "Sitemap: https://www.stataxis.org/sitemap.xml" in robots and "Disallow: /\n" not in robots
    llms = services_cms.llms_txt(s)
    assert "[Custom Research](https://www.stataxis.org/services/custom-research)" in llms and "draft-one" not in llms


def test_the_search_check_says_what_to_fix():
    d = {"name": "X", "slug": "x", "intro": "short", "seo_title": "", "seo_description": "", "seo_keywords": "", "deliverables": [], "faqs": [], "related": [], "audience": [], "limits": [], "steps": []}
    levels = {c["level"] for c in services_cms.seo_report(d)}
    assert "bad" in levels and "warn" in levels
    full = {**services_seed.SERVICES[3], "id": 1, "status": "published", "noindex": False}
    assert not [c for c in services_cms.seo_report(full) if c["level"] != "ok"], [c for c in services_cms.seo_report(full) if c["level"] != "ok"]
    twin = {**full, "id": 2}
    assert any("same as" in c["text"] for c in services_cms.seo_report(twin, [full, twin]))


# ------------------------------------------------------------------------------------------------------------------------------ the right answer for every address
def test_a_moved_address_is_redirected_a_deleted_one_is_gone_and_an_unknown_one_is_not_found():
    s, _ = seeded()
    key = 1
    ok = services_cms.respond(s, key, "/services/custom-research")
    assert ok[0] == 200 and ok[3].startswith('"') and b"<h1" in ok[2]
    row = s.query(Service).filter_by(slug="custom-research").one()
    services_cms.save_service(s, "o", {**services_cms.serialize(row), "slug": "bespoke-research"}, row.id)
    services_cms.invalidate()
    assert services_cms.respond(s, key, "/services/bespoke-research")[0] == 200
    moved = services_cms.respond(s, key, "/services/custom-research")
    assert moved[0] == 301 and moved[4] == "/services/bespoke-research"
    services_cms.delete_service(s, "o", row.id)
    services_cms.invalidate()
    assert services_cms.respond(s, key, "/services/bespoke-research")[0] == 410
    assert services_cms.respond(s, key, "/services/custom-research")[0] == 410 or services_cms.respond(s, key, "/services/custom-research")[0] == 301
    assert services_cms.respond(s, key, "/services/never-existed")[0] == 404
    assert services_cms.respond(s, key, "/services/team-pulse-survey/")[:1] == (301,) and services_cms.respond(s, key, "/services/team-pulse-survey/")[4] == "/services/team-pulse-survey"
    assert services_cms.respond(s, key, "/platform") is None                                                      # not ours: the static files carry on


def test_an_unpublished_service_disappears_at_once_from_the_page_the_menu_and_the_sitemap():
    s, _ = seeded()
    row = s.query(Service).filter_by(slug="team-pulse-survey").one()
    assert services_cms.respond(s, 1, "/services/team-pulse-survey")[0] == 200
    services_cms.set_status(s, "o", row.id, "draft")                                                              # invalidates the kept pages
    assert services_cms.respond(s, 1, "/services/team-pulse-survey")[0] == 404
    assert "team-pulse-survey" not in services_cms.sitemap_xml(s) and "team-pulse-survey" not in json.dumps(services_cms.public_list(s))


# ------------------------------------------------------------------------------------------------------------------------------ the routes
def user(s, email, admin=False):
    u = User(email=email, password_hash=hash_password("a long enough pass"), plan="sx_enterprise", requested_plan="sx_enterprise", is_admin=admin, active=True, approval_status="approved", full_name=email, organization="Org")
    s.add(u)
    s.commit()
    return u


def caller(engine):
    app = cms_application(lambda: Session(engine))

    def call(who, method, path, body=None, query=""):
        raw = json.dumps(body).encode() if body is not None else b""
        out = {}
        env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)),
               "HTTP_AUTHORIZATION": ("Bearer " + issue_token(AuthIdentity(who.id, who.email, who.plan, who.is_admin))) if who else ""}
        res = app(env, lambda status, headers: out.update(status=status, headers=dict(headers)))
        data = b"".join(res)
        return int(out["status"].split()[0]), json.loads(data)
    return call


def test_only_an_administrator_may_edit_and_the_whole_flow_works_over_http():
    s, engine = make_session()
    admin, member = user(s, "admin@x.in", True), user(s, "member@x.in")
    call = caller(engine)
    assert call(None, "GET", "/api/v1/cms/services")[0] == 401
    assert call(member, "GET", "/api/v1/cms/services")[0] == 403
    assert call(member, "POST", "/api/v1/cms/services/save", good())[0] == 403
    code, body = call(admin, "GET", "/api/v1/cms/services")
    assert code == 200 and len(body["services"]) == 11 and body["base_url"] == "https://www.stataxis.org" and body["services"][0]["seo_problems"] == 0      # the starters are written on first use
    code, body = call(admin, "POST", "/api/v1/cms/services/save", good())
    assert code == 200 and body["service"]["status"] == "draft" and body["checks"]
    sid = body["service"]["id"]
    assert call(admin, "POST", "/api/v1/cms/services/save", good(name="Other", slug="brand-pulse"))[0] == 400            # a plain message, not a crash
    code, body = call(admin, "POST", "/api/v1/cms/services/preview", {**good(), "id": sid})
    assert code == 200 and "noindex" in body["html"] and "<h1" in body["html"] and body["checks"]
    assert call(admin, "GET", "/api/v1/cms/services/get", query=f"id={sid}")[1]["service"]["name"] == "Brand Pulse"
    assert call(admin, "POST", "/api/v1/cms/services/status", {"id": sid, "status": "published"})[1]["service"]["status"] == "published"
    assert call(admin, "GET", "/api/v1/cms/services/history", query=f"id={sid}")[1]["revisions"][0]["action"] == "publish"
    assert call(admin, "POST", "/api/v1/cms/services/order", {"ids": [sid]})[1]["services"][0]["id"] == sid
    assert call(admin, "POST", "/api/v1/cms/services/page", {"heading": "Services we offer"})[1]["page"]["heading"] == "Services we offer"
    assert call(admin, "POST", "/api/v1/cms/services/delete", {"id": sid})[1]["deleted"] == "brand-pulse"
    assert call(admin, "GET", "/api/v1/cms/services/get", query="id=99999")[0] == 404
    assert call(admin, "POST", "/api/v1/cms/nothing", {"x": 1})[0] == 404


def serve(engine, path, method="GET", **env):
    out = {}
    res = site_response(lambda: Session(engine), {"REQUEST_METHOD": method, "PATH_INFO": path, **env}, lambda status, headers: out.update(status=status, headers=dict(headers)), [("X-Test", "1")])
    return (None, None, None) if res is None else (int(out["status"].split()[0]), out["headers"], b"".join(res))


def test_the_public_pages_answer_with_etags_head_requests_and_the_right_codes():
    s, engine = make_session()
    code, headers, body = serve(engine, "/services/custom-research")
    assert code == 200 and headers["Content-Type"].startswith("text/html") and headers["X-Test"] == "1" and b"<h1" in body and int(headers["Content-Length"]) == len(body)
    assert serve(engine, "/services/custom-research", **{"HTTP_IF_NONE_MATCH": headers["ETag"]})[0] == 304
    code, _, body = serve(engine, "/services/custom-research", method="HEAD")
    assert code == 200 and body == b""
    assert serve(engine, "/services")[0] == 200 and serve(engine, "/sitemap.xml")[1]["Content-Type"].startswith("application/xml") and serve(engine, "/llms.txt")[0] == 200
    code, headers, _ = serve(engine, "/services/nope")
    assert code == 404 and headers["X-Robots-Tag"] == "noindex"
    code, headers, _ = serve(engine, "/services/custom-research/")
    assert code == 301 and headers["Location"] == "/services/custom-research"
    assert serve(engine, "/services", method="POST")[0] is None and serve(engine, "/platform")[0] is None
    Base.metadata.drop_all(engine)                                                                                # even with no database at all, robots.txt still answers
    assert serve(engine, "/robots.txt")[0] == 200 and b"Sitemap:" in serve(engine, "/robots.txt")[2]


def test_the_seed_flag_stops_a_second_seeding_even_when_every_service_is_deleted():
    s, _ = seeded()
    for r in services_cms.list_services(s):
        services_cms.delete_service(s, "o", r["id"])
    services_cms.ensure_seed(s)
    assert s.query(Service).count() == 0 and s.get(AppSetting, services_cms.SEEDED_KEY) is not None
    assert "<loc>https://www.stataxis.org/services" not in services_cms.sitemap_xml(s)                           # no empty Services section is announced


# ------------------------------------------------------------------------------------------------------------------------------ the web app and the pages around it
def test_the_web_app_serves_the_services_robots_sitemap_and_list_and_keeps_the_editing_api_private():
    import web

    def get(path):
        out = {}
        res = web.application({"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "", "REMOTE_ADDR": "127.0.0.1"}, lambda status, headers: out.update(status=status, headers=dict(headers)))
        return out["status"], out["headers"], b"".join(res)
    status, headers, body = get("/services")
    assert status.startswith("200") and b"/services/custom-research" in body and headers["Content-Security-Policy"] and headers["X-Content-Type-Options"] == "nosniff"
    assert get("/services/custom-research")[0].startswith("200") and get("/services/nothing-here")[0].startswith("404")
    assert get("/robots.txt")[0].startswith("200") and b"Sitemap:" in get("/robots.txt")[2] and get("/sitemap.xml")[0].startswith("200") and get("/llms.txt")[0].startswith("200")
    status, _, body = get("/api/v1/public/services")
    assert status.startswith("200") and len(json.loads(body)["services"]) >= 1
    assert get("/api/v1/cms/services")[0].startswith("401")


def test_the_menu_footer_and_workspace_know_about_the_services():
    site = (DASH / "site.js").read_text(encoding="utf-8")
    assert '["/services", "Services"]' in site and "/api/v1/public/services" in site and "vx-dd-list" in site
    assert "cms.js" in (DASH / "workspace.html").read_text(encoding="utf-8") and 'add("adm-services"' in (DASH / "cms.js").read_text(encoding="utf-8")
