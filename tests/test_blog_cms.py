"""The blog CMS: writing, scheduling and publishing articles, the history, the safe text format, the pages the server writes (and what a search engine reads in them), the Insights list, the sitemap, moved and
removed addresses, the editing routes, and the guarantee that the six built-in articles are never touched. Invented data in a scratch database."""
import io
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import blog_cms, services_cms
from api.auth import AuthIdentity, hash_password, issue_token
from api.services_http import cms_application, site_response
from collector.storage import Base, Post, User

DASH = Path(__file__).resolve().parent.parent / "dashboard"
LONG = " ".join(["Audiences move and a good article says exactly how much they moved."] * 12)


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    blog_cms.invalidate()
    services_cms.invalidate()


def make_session():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return Session(engine), engine


def article(**over):
    base = {"title": "Why the median beats the average", "excerpt": "A short and honest summary of the article.", "category": "Method", "body": "## First idea\n\n" + LONG + "\n\n## Second idea\n\nSee the [platform](/platform).\n\n" + LONG,
            "seo_keywords": "median audience"}
    return {**base, **over}


def test_an_article_is_saved_as_a_draft_published_and_every_change_is_kept():
    s, _ = make_session()
    a = blog_cms.save_post(s, "ever@x.in", article())
    assert a["slug"] == "why-the-median-beats-the-average" and a["status"] == "draft" and not a["live"] and a["author"] == "StatAxis" and a["words"] > 100 and a["published_at"] is None
    assert blog_cms.live_posts(s) == []
    p = blog_cms.set_status(s, "ever@x.in", a["id"], "published")
    assert p["live"] and p["state"] == "published" and p["published_at"]
    first_date = p["published_at"]
    blog_cms.save_post(s, "ever@x.in", article(excerpt="A changed summary of the article."), a["id"])
    assert blog_cms.get_post(s, a["id"]).published_at.isoformat()[:19] == first_date[:19]                      # editing does not move the publication date
    assert [r["action"] for r in blog_cms.revisions(s, a["id"])][:3] == ["update", "publish", "create"]
    blog_cms.set_status(s, "ever@x.in", a["id"], "draft")
    assert blog_cms.revisions(s, a["id"])[0]["action"] == "unpublish" and blog_cms.live_posts(s) == []


def test_what_a_person_must_fix_is_said_plainly():
    s, _ = make_session()
    with pytest.raises(ValueError, match="title cannot be empty"):
        blog_cms.save_post(s, "o", article(title=" "))
    with pytest.raises(ValueError, match="built into the site"):
        blog_cms.save_post(s, "o", article(slug="ifx-score-explained"))                                         # an address of a built-in article can never be taken
    with pytest.raises(ValueError, match="to publish or schedule"):
        blog_cms.save_post(s, "o", {"title": "Thin", "status": "published", "body": "too short"})
    assert blog_cms.save_post(s, "o", {"title": "Thin one", "body": "too short"})["status"] == "draft"          # a draft may be unfinished
    blog_cms.save_post(s, "o", article())
    with pytest.raises(ValueError, match="already used"):
        blog_cms.save_post(s, "o", article(slug="why-the-median-beats-the-average"))
    with pytest.raises(ValueError, match="canonical"):
        blog_cms.save_post(s, "o", article(title="Other", canonical_url="https://example.com/x"))
    with pytest.raises(ValueError, match="choose the date"):
        blog_cms.save_post(s, "o", article(title="Later", status="scheduled"))
    with pytest.raises(ValueError, match="not a valid date"):
        blog_cms.save_post(s, "o", article(title="Later two", status="scheduled", publish_at="soon"))


def test_a_scheduled_article_goes_live_by_itself_at_its_time():
    s, _ = make_session()
    soon = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    a = blog_cms.save_post(s, "o", article(status="scheduled", publish_at=soon))
    assert a["state"] == "scheduled" and not a["live"] and blog_cms.live_posts(s) == [] and a["published_at"]
    row = s.get(Post, a["id"])
    assert not blog_cms.is_live(row, datetime.now(UTC)) and blog_cms.is_live(row, datetime.now(UTC) + timedelta(hours=3))   # nothing has to be pressed when the time comes
    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    b = blog_cms.save_post(s, "o", article(title="Already due", status="scheduled", publish_at=past))
    assert b["live"] and [p["slug"] for p in blog_cms.live_posts(s)] == ["already-due"]


def test_an_earlier_version_comes_back_as_a_draft_and_a_deleted_article_can_return():
    s, _ = make_session()
    a = blog_cms.save_post(s, "o", article(excerpt="First summary of this article."))
    blog_cms.save_post(s, "o", article(excerpt="Second summary of this article."), a["id"])
    first = [r for r in blog_cms.revisions(s, a["id"]) if r["action"] == "create"][0]
    back = blog_cms.restore(s, "o", first["id"])
    assert back["excerpt"] == "First summary of this article." and back["status"] == "draft"
    blog_cms.delete_post(s, "o", a["id"])
    assert s.get(Post, a["id"]) is None and blog_cms.deleted_revisions(s)[0]["slug"] == "why-the-median-beats-the-average"
    gone = blog_cms.deleted_revisions(s)[0]["id"]
    assert blog_cms.restore(s, "o", gone)["slug"] == "why-the-median-beats-the-average" and blog_cms.deleted_revisions(s) == []


def test_the_text_format_is_simple_and_safe():
    html = blog_cms.render_body("## Heading\n\nA paragraph with **bold**, *italic* and a [link](/platform) and [out](https://example.org/x).\n\n- one\n- two\n\n1. first\n2. second\n\n> a quote\n\n### Small")
    assert "<h2>Heading</h2>" in html and "<strong>bold</strong>" in html and "<em>italic</em>" in html and '<a href="/platform">link</a>' in html
    assert '<a href="https://example.org/x" rel="noopener noreferrer" target="_blank">out</a>' in html and "<ul><li>one</li><li>two</li></ul>" in html and "<ol><li>first</li><li>second</li></ol>" in html
    assert "<blockquote>a quote</blockquote>" in html and "<h3>Small</h3>" in html
    evil = blog_cms.render_body('<script>alert(1)</script> [x](javascript:alert(1)) [y](//evil.com) <img src=x onerror=alert(1)>\n\n## <b>h</b>')
    assert "<script>" not in evil and "<img" not in evil and 'href="javascript' not in evil and 'href="//evil' not in evil and "<b>h</b>" not in evil


def live_article(s, **over):
    a = blog_cms.save_post(s, "o", article(**over))
    return blog_cms.set_status(s, "o", a["id"], "published")


def ld_blocks(html):
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


def test_an_article_page_carries_everything_a_search_engine_looks_for():
    s, _ = make_session()
    a = live_article(s, seo_title="Median beats average: how to read audiences", seo_description="Why the median audience tells you more than the average, and how to use it when you plan and buy media.")
    html = blog_cms.render_post(a, [])
    assert html.count("<h1") == 1 and '<html lang="en-IN">' in html and '<link rel="canonical" href="https://www.stataxis.org/blog/why-the-median-beats-the-average">' in html
    assert 'content="index,follow' in html and 'property="og:type" content="article"' in html and 'property="article:published_time"' in html and 'property="og:title" content="Median beats average: how to read audiences"' in html
    kinds = {b["@type"] for b in ld_blocks(html)}
    assert kinds == {"Article", "BreadcrumbList"}
    ld = next(b for b in ld_blocks(html) if b["@type"] == "Article")
    assert ld["headline"] == a["title"] and ld["datePublished"] == a["published_at"][:10] and ld["author"]["name"] == "StatAxis" and ld["wordCount"] == a["words"] and ld["mainEntityOfPage"].endswith("/blog/why-the-median-beats-the-average")
    assert "vx-art-head" in html and "vx-prose" in html and "<h2>First idea</h2>" in html and 'href="/insights"' in html and 'src="/site.js"' in html
    person = blog_cms.render_post({**a, "author": "Asha Rao"}, [])
    assert next(b for b in ld_blocks(person) if b["@type"] == "Article")["author"] == {"@type": "Person", "name": "Asha Rao"}
    assert 'content="noindex,follow"' in blog_cms.render_post(a, [], preview=True) and 'content="noindex,follow"' in blog_cms.render_post({**a, "noindex": True}, [])


def test_the_insights_list_shows_live_articles_first_and_never_breaks_the_page():
    s, engine = make_session()
    page = (DASH / "insights.html").read_bytes()
    assert blog_cms.inject_cards(lambda: Session(engine), page) == page                                          # nothing live: the page is byte for byte the same
    live_article(s)
    blog_cms.save_post(s, "o", article(title="A draft only"))
    out = blog_cms.inject_cards(lambda: Session(engine), page)
    marker = b'<div class="vx-posts">'
    assert out.count(b"/blog/why-the-median-beats-the-average") == 1 and b"A draft only" not in out and out.index(b"/blog/why-the-median") < out.index(b"/blog/average-beats-peak")
    assert out.replace(blog_cms.cards(blog_cms.live_posts(s)).encode(), b"", 1) == page and marker in page   # nothing else of the page changed
    assert blog_cms.inject_cards(lambda: (_ for _ in ()).throw(RuntimeError("db down")), page) == page          # a database failure leaves the page as it was


def test_the_sitemap_and_llms_list_live_articles_only():
    s, _ = make_session()
    a = live_article(s)
    blog_cms.save_post(s, "o", article(title="Hidden draft"))
    blog_cms.save_post(s, "o", article(title="Noindexed", noindex=True, status="published"))
    sm = services_cms.sitemap_xml(s)
    assert f"/blog/{a['slug']}" in sm and "hidden-draft" not in sm and "noindexed" not in sm and "/blog/ifx-score-explained" in sm
    llms = services_cms.llms_txt(s)
    assert f"/blog/{a['slug']}" in llms and "hidden-draft" not in llms


def test_the_search_check_says_what_to_fix():
    thin = {"title": "X", "slug": "x", "body": "short", "seo_title": "", "seo_description": "", "seo_keywords": "", "excerpt": "", "category": ""}
    levels = {c["level"] for c in blog_cms.seo_report(thin)}
    assert "bad" in levels and "warn" in levels
    s, _ = make_session()
    a = blog_cms.save_post(s, "o", article(body="## One\n\nThe median audience matters. " + LONG + "\n\n## Two\n\nMore on the median audience and [how we measure](/methodology). " + LONG,
                                           seo_title="Median audience: how to read it before you buy", seo_description="What the median audience says that the average hides, and how to use it when you plan and buy media."))
    bad = [c for c in blog_cms.seo_report(a) if c["level"] != "ok"]
    assert [c["text"] for c in bad] == [c["text"] for c in bad if "words" in c["text"]], bad                      # only the length is left to improve in this short invented text
    twin = blog_cms.save_post(s, "o", article(title="Twin", seo_title=a["seo_title"], seo_description=a["seo_description"]))
    a_live = {**a, "live": True}
    assert any("same as" in c["text"] for c in blog_cms.seo_report(twin, [a_live]))


def test_moved_removed_and_not_yet_live_addresses_get_the_right_answer():
    s, _ = make_session()
    a = live_article(s)
    key = 7
    ok = blog_cms.respond(s, key, "/blog/why-the-median-beats-the-average")
    assert ok[0] == 200 and b"<h1" in ok[2] and ok[3].startswith('"')
    blog_cms.save_post(s, "o", article(slug="median-beats-average"), a["id"])
    blog_cms.invalidate()
    assert blog_cms.respond(s, key, "/blog/median-beats-average")[0] == 200
    moved = blog_cms.respond(s, key, "/blog/why-the-median-beats-the-average")
    assert moved[0] == 301 and moved[4] == "/blog/median-beats-average"
    blog_cms.set_status(s, "o", a["id"], "draft")
    blog_cms.invalidate()
    assert blog_cms.respond(s, key, "/blog/median-beats-average")[0] == 404                                      # unpublished: gone from the web at once
    blog_cms.delete_post(s, "o", a["id"])
    assert blog_cms.respond(s, key, "/blog/median-beats-average")[0] == 410 and blog_cms.respond(s, key, "/blog/why-the-median-beats-the-average")[0] == 410
    assert blog_cms.respond(s, key, "/blog/never-existed") is None and blog_cms.respond(s, key, "/blog/ifx-score-explained") is None   # not ours: the file or the 404 page answers
    assert blog_cms.respond(s, key, "/blog/") is None and blog_cms.respond(s, key, "/blog/a/b") is None


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
        return int(out["status"].split()[0]), json.loads(b"".join(res))
    return call


def test_only_an_administrator_may_write_and_the_whole_flow_works_over_http():
    s, engine = make_session()
    admin, member = user(s, "admin@x.in", True), user(s, "member@x.in")
    call = caller(engine)
    assert call(None, "GET", "/api/v1/cms/posts")[0] == 401 and call(member, "GET", "/api/v1/cms/posts")[0] == 403 and call(member, "POST", "/api/v1/cms/posts/save", article())[0] == 403
    code, body = call(admin, "GET", "/api/v1/cms/posts")
    assert code == 200 and body["posts"] == [] and len(body["builtin"]) == 6 and "Method" in body["categories"] and body["builtin"][0]["title"]
    code, body = call(admin, "POST", "/api/v1/cms/posts/save", article())
    assert code == 200 and body["post"]["state"] == "draft" and body["checks"]
    pid = body["post"]["id"]
    assert call(admin, "POST", "/api/v1/cms/posts/save", article(title="Other", slug="why-the-median-beats-the-average"))[0] == 400
    code, body = call(admin, "POST", "/api/v1/cms/posts/preview", {**article(), "id": pid})
    assert code == 200 and "noindex" in body["html"] and "<article" in body["html"]
    assert call(admin, "GET", "/api/v1/cms/posts/get", query=f"id={pid}")[1]["post"]["title"] == "Why the median beats the average"
    assert call(admin, "POST", "/api/v1/cms/posts/status", {"id": pid, "status": "published"})[1]["post"]["live"] is True
    assert call(admin, "GET", "/api/v1/cms/posts/history", query=f"id={pid}")[1]["revisions"][0]["action"] == "publish"
    when = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    code, body = call(admin, "POST", "/api/v1/cms/posts/save", article(title="Tomorrow", status="scheduled", publish_at=when))
    assert code == 200 and body["post"]["state"] == "scheduled"
    assert call(admin, "POST", "/api/v1/cms/posts/delete", {"id": pid})[1]["deleted"] == "why-the-median-beats-the-average"
    assert call(admin, "GET", "/api/v1/cms/posts/get", query="id=99999")[0] == 404


def serve(engine, path, method="GET", **env):
    out = {}
    res = site_response(lambda: Session(engine), {"REQUEST_METHOD": method, "PATH_INFO": path, **env}, lambda status, headers: out.update(status=status, headers=dict(headers)), [])
    return (None, None, None) if res is None else (int(out["status"].split()[0]), out["headers"], b"".join(res))


def test_the_public_article_pages_answer_with_etags_and_leave_the_built_in_articles_alone():
    s, engine = make_session()
    live_article(s)
    code, headers, body = serve(engine, "/blog/why-the-median-beats-the-average")
    assert code == 200 and b"<h1" in body and headers["Content-Type"].startswith("text/html") and int(headers["Content-Length"]) == len(body)
    assert serve(engine, "/blog/why-the-median-beats-the-average", **{"HTTP_IF_NONE_MATCH": headers["ETag"]})[0] == 304
    assert serve(engine, "/blog/why-the-median-beats-the-average", method="HEAD")[2] == b""
    assert serve(engine, "/blog/ifx-score-explained") == (None, None, None)                                      # the built-in article is served from its file, untouched
    assert serve(engine, "/blog/unknown") == (None, None, None)
    blog_cms.save_post(s, "o", article(title="Not live"))
    code, headers, _ = serve(engine, "/blog/not-live")
    assert code == 404 and headers["X-Robots-Tag"] == "noindex"


def test_the_six_built_in_articles_are_still_served_from_their_files_by_the_web_app():
    import web
    for f in sorted((DASH / "blog").glob("*.html")):
        out = {}
        res = web.application({"REQUEST_METHOD": "GET", "PATH_INFO": f"/blog/{f.stem}", "QUERY_STRING": "", "REMOTE_ADDR": "127.0.0.1"}, lambda status, headers: out.update(status=status))
        assert out["status"].startswith("200") and b"".join(res) == f.read_bytes(), f.name


def test_the_menu_and_workspace_know_about_the_blog_screen():
    ws = (DASH / "workspace.html").read_text(encoding="utf-8")
    assert '"adm-blog"' in ws and 'add("adm-blog"' in (DASH / "cms.js").read_text(encoding="utf-8")
