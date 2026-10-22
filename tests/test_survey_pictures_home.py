"""Pictures in polls (a logo on an option, a picture above a question, the survey's own logo) and the home page promotion of open polls (a section straight after the top banner, and a pop-up).
Invented data in a scratch database."""
import base64
import io
import json
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import survey_core as core
from api import survey_pages
from api.auth import AuthIdentity, hash_password, issue_token
from api.rate_limit import limiter
from api.survey_http import inject_home_polls, survey_admin_application, survey_site_response
from collector.storage import Base, Survey, SurveyImage, User

DASH = Path(__file__).resolve().parent.parent / "dashboard"
INDEX = (DASH / "index.html").read_bytes()
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    limiter.reset()
    from api import survey_http
    survey_http._HOME.clear()


def make():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return Session(engine), engine


def png(size=(300, 200), color=(200, 20, 20), mode="RGB", fmt="PNG", **kw):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, fmt, **kw)
    return buf.getvalue()


def poll(**over):
    base = {"title": "Which logo?", "kind": "poll", "status": "live", "questions": [{"type": "single", "text": "Pick one", "required": True, "options": [{"text": "A"}, {"text": "B"}]}]}
    return {**base, **over}


# ------------------------------------------------------------------------------------------------------------------------------ pictures
def test_a_picture_is_checked_shrunk_cleaned_and_kept_as_webp():
    data, w, h = core.process_image(png((2000, 1000)), "option")
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP" and (w, h) == (480, 240)
    assert core.process_image(png((3000, 3000)), "question")[1:] == (1200, 1200) and core.process_image(png((100, 50)), "logo")[1:] == (100, 50)       # never enlarged
    rgba = Image.open(io.BytesIO(core.process_image(png((50, 50), (255, 0, 0, 0), "RGBA"))[0]))
    assert rgba.mode == "RGBA" and rgba.getpixel((1, 1))[3] == 0                                                         # a transparent logo stays transparent
    gif = png((40, 40), (0, 0, 255), "P", "GIF")
    assert core.process_image(gif)[0][:4] == b"RIFF"
    tall = Image.new("RGB", (100, 200), (10, 200, 10))
    exif = Image.Exif()
    exif[274] = 6                                                                                                        # "rotate 90 degrees"
    exif[34853] = {1: "N"}
    buf = io.BytesIO()
    tall.save(buf, "JPEG", exif=exif)
    out = Image.open(io.BytesIO(core.process_image(buf.getvalue())[0]))
    assert out.size == (200, 100) and not out.getexif()                                                                  # turned upright, camera and place data gone


@pytest.mark.parametrize("raw,why", [
    (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "Only PNG"),
    (b"<html><script>alert(1)</script></html>", "Only PNG"),
    (b"GIF89a" + b"not really a gif" * 5, "not a picture"),
    (b"\x89PNG\r\n\x1a\n" + b"truncated", "not a picture"),
    (b"plain text pretending", "Only PNG"),
    (b"", "Only PNG"),
])
def test_files_that_are_not_pictures_are_refused(raw, why):
    with pytest.raises(ValueError, match=why):
        core.process_image(raw)


def test_a_picture_that_is_too_big_in_bytes_or_in_pixels_is_refused():
    with pytest.raises(ValueError, match="too large"):
        core.process_image(b"\x89PNG\r\n\x1a\n" + b"0" * (core.MAX_UPLOAD_BYTES + 1))
    with pytest.raises(ValueError, match="too many pixels"):
        core.process_image(png((7000, 7000)))                                                                              # 49 million pixels, tiny file


def test_stored_pictures_get_random_keys_and_unused_old_ones_are_cleared():
    s, _ = make()
    a = core.store_image(s, "logo<script>.png", png(), "o")
    assert len(a["key"]) == 20 and a["url"] == f"/survey-img/{a['key']}.webp" and s.query(SurveyImage).one().filename == "logoscript.png"                  # a file name is cleaned
    old = SurveyImage(key="1" * 20, survey_id=None, data=b"x", created_at=NOW - timedelta(days=3))
    kept = SurveyImage(key="2" * 20, survey_id=7, data=b"x", created_at=NOW - timedelta(days=3))
    s.add_all([old, kept])
    s.commit()
    core.store_image(s, "b.png", png(), "o")
    assert {i.key for i in s.query(SurveyImage).all()} >= {"2" * 20} and "1" * 20 not in {i.key for i in s.query(SurveyImage).all()}                           # unused for two days: cleared; used: kept


def test_pictures_belong_to_the_survey_that_uses_them_and_travel_with_copies():
    s, _ = make()
    a, b, logo = (core.store_image(s, f"{n}.png", png(color=c), "o") for n, c in (("a", (255, 0, 0)), ("b", (0, 255, 0)), ("logo", (0, 0, 255))))
    q = [{"type": "single", "text": "Pick", "image": a["key"], "required": True, "options": [{"text": "A", "image": a["key"]}, {"text": "B", "image": b["key"]}, {"text": "C", "image": "not-a-key"}]}]
    saved = core.save_survey(s, "o", poll(questions=q, logo_image=logo["key"]))
    assert saved["questions"][0]["options"][1]["image"] == b["key"] and "image" not in saved["questions"][0]["options"][2] and saved["logo_url"] == logo["url"]    # a malformed key is dropped
    assert {i.survey_id for i in s.query(SurveyImage).all()} == {saved["id"]}                                              # attached on save
    with pytest.raises(ValueError, match="missing"):
        core.save_survey(s, "o", poll(title="Other poll", questions=[{"type": "single", "text": "X", "options": [{"text": "A", "image": "f" * 20}, {"text": "B"}]}]))
    with pytest.raises(ValueError, match="another survey"):
        core.save_survey(s, "o", poll(title="Third poll", questions=[{"type": "single", "text": "X", "options": [{"text": "A", "image": a["key"]}, {"text": "B"}]}]))
    copy = core.duplicate_survey(s, "o", saved["id"])
    assert copy["questions"][0]["options"][1]["image"] != b["key"] and copy["logo_image"] != logo["key"] and s.query(SurveyImage).count() == 6
    row = core.get_survey(s, saved["id"])
    row.status = "draft"
    s.commit()
    core.delete_survey(s, "o", saved["id"])
    assert s.query(SurveyImage).count() == 3 and all(i.survey_id == copy["id"] for i in s.query(SurveyImage).all())          # deleting one survey leaves the copy's pictures


def test_the_respondent_and_the_results_get_picture_addresses_only_for_what_is_live():
    s, _ = make()
    a = core.store_image(s, "a.png", png(), "o")
    logo = core.store_image(s, "l.png", png(), "o")
    saved = core.save_survey(s, "o", poll(questions=[{"type": "single", "text": "Pick", "image": a["key"], "options": [{"text": "A", "image": a["key"]}, {"text": "B"}]}], logo_image=logo["key"], results_mode="public", min_results=0))
    row = core.get_survey(s, saved["id"])
    defn = core.public_definition(row)
    assert defn["logo_url"] == logo["url"] and defn["questions"][0]["image_url"] == a["url"] and defn["questions"][0]["options"][0]["image_url"] == a["url"] and "image_url" not in defn["questions"][0]["options"][1]
    core.submit_response(s, row, {"q1": {"o": "o1"}}, token="t" * 20, now=NOW, started_ms=(NOW - timedelta(seconds=60)).timestamp() * 1000)
    assert core.survey_results(s, row)["questions"][0]["options"][0]["image_url"] == a["url"] and core.public_results(row, s)["questions"][0]["options"][0]["image_url"] == a["url"]
    html = survey_pages.survey_page(defn, None, indexable=False)
    assert f'class="brandlogo" src="{logo["url"]}"' in html and f'property="og:image" content="https://www.stataxis.org{logo["url"]}"' in html and "summary_large_image" in html and "/assets/stataxis-logo.svg" not in html


# ------------------------------------------------------------------------------------------------------------------------------ routes
def admin_call(engine):
    app = survey_admin_application(lambda: Session(engine))

    def call(who, route, body):
        raw = json.dumps(body).encode()
        out = {}
        env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/v1/surveys/" + route, "QUERY_STRING": "", "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)),
               "HTTP_AUTHORIZATION": ("Bearer " + issue_token(AuthIdentity(who.id, who.email, who.plan, who.is_admin))) if who else ""}
        res = app(env, lambda status, headers: out.update(status=status))
        return int(out["status"].split()[0]), json.loads(b"".join(res))
    return call


def user(s, email, admin=False):
    u = User(email=email, password_hash=hash_password("a long enough pass"), plan="sx_enterprise", requested_plan="sx_enterprise", is_admin=admin, active=True, approval_status="approved", full_name=email, organization="Org")
    s.add(u)
    s.commit()
    return u


def b64(raw, prefix=True):
    return ("data:image/png;base64," if prefix else "") + base64.b64encode(raw).decode()


def test_only_an_administrator_uploads_and_bad_files_get_a_plain_answer():
    s, engine = make()
    admin, member = user(s, "admin@x.in", True), user(s, "member@x.in")
    call = admin_call(engine)
    assert call(None, "images/upload", {"data": b64(png())})[0] == 401 and call(member, "images/upload", {"data": b64(png())})[0] == 403
    code, body = call(admin, "images/upload", {"filename": "logo.png", "data": b64(png((900, 900))), "purpose": "option"})
    assert code == 200 and body["width"] == 480 and body["url"].endswith(".webp")
    assert call(admin, "images/upload", {"data": b64(png(), prefix=False), "purpose": "logo"})[0] == 200                      # a bare base64 string works too
    code, body = call(admin, "images/upload", {"data": b64(b"<svg onload=alert(1)>")})
    assert code == 400 and "Only PNG" in body["error"]
    code, body = call(admin, "images/upload", {"data": "!!!not base64!!!"})
    assert code == 400 and "could not be read" in body["error"]
    assert call(admin, "images/upload", {"data": b64(png(), prefix=False), "purpose": "nonsense"})[0] == 200                  # an unknown use falls back to the option size


def page(engine, path, method="GET", **env):
    out = {}
    res = survey_site_response(lambda: Session(engine), {"REQUEST_METHOD": method, "PATH_INFO": path, **env}, lambda status, headers: out.update(status=status, headers=dict(headers)), [("X-Test", "1")])
    return (None, None, b"") if res is None else (int(out["status"].split()[0]), out["headers"], b"".join(res))


def test_pictures_are_served_as_sandboxed_images_that_browsers_may_keep():
    s, engine = make()
    key = core.store_image(s, "a.png", png(), "o")["key"]
    code, headers, body = page(engine, f"/survey-img/{key}.webp")
    assert code == 200 and body[:4] == b"RIFF" and headers["Content-Type"] == "image/webp" and "immutable" in headers["Cache-Control"] and headers["Content-Security-Policy"] == "default-src 'none'; sandbox" and headers["X-Test"] == "1"
    assert headers["X-Content-Type-Options"] == "nosniff" and int(headers["Content-Length"]) == len(body)
    assert page(engine, f"/survey-img/{key}.webp", **{"HTTP_IF_NONE_MATCH": headers["ETag"]})[0] == 304 and page(engine, f"/survey-img/{key}.webp", method="HEAD")[2] == b""
    for bad in (f"/survey-img/{key}.png", f"/survey-img/{key}", "/survey-img/" + "0" * 20 + ".webp", "/survey-img/../../etc/passwd.webp", "/survey-img/.webp", f"/survey-img/{key.upper()}.webp"):
        assert page(engine, bad)[0] == 404, bad


def test_the_scripts_of_the_home_popup_and_the_poll_pages_parse():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    with tempfile.TemporaryDirectory() as d:
        for name, text in (("form.js", survey_pages.JS), ("home.js", survey_pages.HOME_JS)):
            path = Path(d) / name
            path.write_text(text, encoding="utf-8")
            done = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
            assert done.returncode == 0, (name, done.stderr[:400])
        done = subprocess.run([node, "--check", str(DASH / "surveys.js")], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr[:400]


# ------------------------------------------------------------------------------------------------------------------------------ the home page
def test_only_open_public_promoted_polls_are_chosen_newest_first_and_at_most_three():
    s, _ = make()
    q = poll()["questions"]
    for title, over in (("Old poll", {}), ("Invite only", {"access": "invite"}), ("Draft one", {"status": "draft"}), ("Closed one", {"status": "closed"}), ("Not promoted", {"promote": False}),
                        ("Full one", {"max_responses": 1}), ("Future one", {"opens_at": (datetime.now(UTC) + timedelta(days=2)).isoformat()}), ("Second poll", {}), ("Third poll", {}), ("Fourth poll", {"kind": "survey"}),
                        ("Hindi poll", {"language": "hi"})):
        core.save_survey(s, "o", poll(title=title, questions=q, **over))
    full = core.get_survey(s, [x["id"] for x in core.list_surveys(s) if x["title"] == "Full one"][0])
    core.submit_response(s, full, {"q1": {"o": "o1"}}, token="f" * 20, now=datetime.now(UTC), started_ms=(datetime.now(UTC) - timedelta(seconds=60)).timestamp() * 1000)
    items = core.home_polls(s)
    assert [i["title"] for i in items] == ["Hindi poll", "Fourth poll", "Third poll"] and items[0]["cta"] == "पोल में भाग लें" and items[1]["cta"] == "Take the survey" and items[2]["cta"] == "Take the poll"
    assert [i["title"] for i in core.home_polls(s, limit=10)] == ["Hindi poll", "Fourth poll", "Third poll", "Second poll", "Old poll"]


def test_with_no_open_poll_the_home_page_is_byte_for_byte_unchanged():
    s, engine = make()
    assert survey_pages.inject_home(INDEX, []) == INDEX and inject_home_polls(lambda: Session(engine), INDEX) == INDEX
    core.save_survey(s, "o", poll(status="draft"))
    assert inject_home_polls(lambda: Session(engine), INDEX) == INDEX


def test_a_live_poll_gets_a_section_right_after_the_hero_and_a_popup_and_nothing_else_changes():
    s, engine = make()
    logo = core.store_image(s, "l.png", png(), "o")
    core.save_survey(s, "o", poll(title="Which logo? <script>alert(1)</script>", slug="logo-poll", description="Tell us which one you like.", logo_image=logo["key"]))
    core.save_survey(s, "o", poll(title="Second poll", slug="second-poll"))
    out = inject_home_polls(lambda: Session(engine), INDEX).decode("utf-8")
    text = INDEX.decode("utf-8")
    hero_end = text.index("</section>", text.index('<section class="vx-hero"')) + len("</section>")
    first_section = out.index('<section class="vx-sec sxpoll"')
    assert out[hero_end:].startswith("<style>") and out.index("</style>", hero_end) < first_section < out.index('<section class="sx-section">')   # straight after the hero
    assert out.index('<section class="sx-section">') > first_section                                                       # it is the second section: before the sections that were second, not at the bottom
    assert out.index('<section class="vx-hero"') < first_section and out.count('id="live-polls"') == 1
    assert 'href="/survey/second-poll"' in out and 'href="/survey/logo-poll"' in out and "Take the poll" in out and f'src="{logo["url"]}"' in out
    assert 'id="sxpop"' in out and out.rindex('id="sxpop"') > out.index("</main>") and out.index('id="sxpop"') < out.rindex("</body>")                         # the popup sits before the end of the page
    assert out.count('data-go href="/survey/second-poll"') == 1                                                             # the popup shows the newest poll
    assert "<script>alert(1)</script>" not in out.replace("\\u003c", "<") or "&lt;script&gt;alert(1)" in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out and "<h3 id=\"sxpop-t\">Second poll" in out
    section, popup = survey_pages.home_blocks(core.home_polls(s))
    assert out.replace(section, "").replace(popup, "") == text                                                              # remove what was added and the original page is exactly what is left


def test_switching_a_poll_off_or_closing_it_takes_it_off_the_home_page_at_once():
    s, engine = make()
    admin = user(s, "admin@x.in", True)
    call = admin_call(engine)
    saved = call(admin, "save", poll(title="Home poll", slug="home-poll"))[1]["survey"]
    factory = lambda: Session(engine)  # noqa: E731
    assert b'href="/survey/home-poll"' in inject_home_polls(factory, INDEX)
    assert call(admin, "save", {**saved, "promote": False})[0] == 200
    assert inject_home_polls(factory, INDEX) == INDEX                                                                         # the saved choice shows at once, not after the short wait
    call(admin, "save", {**saved, "promote": True})
    assert b'href="/survey/home-poll"' in inject_home_polls(factory, INDEX)
    assert call(admin, "status", {"id": saved["id"], "status": "closed"})[0] == 200
    assert inject_home_polls(factory, INDEX) == INDEX


def test_a_failure_reading_the_polls_leaves_the_home_page_as_it_was():
    def broken():
        raise RuntimeError("database down")
    assert inject_home_polls(broken, INDEX) == INDEX


def test_the_home_page_is_still_served_by_the_web_app():
    import web
    out = {}
    res = web.application({"REQUEST_METHOD": "GET", "PATH_INFO": "/", "QUERY_STRING": "", "REMOTE_ADDR": "127.0.0.1"}, lambda st, h: out.update(st=st))
    body = b"".join(res)
    assert out["st"].startswith("200") and b"Stand on the right axis." in body
