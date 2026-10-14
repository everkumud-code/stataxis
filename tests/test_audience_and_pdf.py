"""Audience geography and age (only where really known), the planner's target audience, and the branded, machine-unreadable PDF."""
import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import audience
from api.admin_http import admin_application
from api.auth import AuthIdentity, issue_token
from api.market_http import market_application
from api.market_tools import media_plan
from api.report_builder import build_report
from collector.storage import AudienceProfile, Base, Channel, Observation, User, Video

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
SHIFT = timedelta(hours=5, minutes=30)


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")


def make():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return Session(engine), engine


def chan(s, key, name):
    c = Channel(youtube_channel_id=key, name=name, network="n", language="Hindi", region="India", segment="news")
    s.add(c)
    s.flush()
    return c


def live(s, c, key, level):
    v = Video(youtube_video_id=key, channel_id=c.id, title=key, topic="Politics", live_started_at=NOW - timedelta(days=60))
    s.add(v)
    s.flush()
    for i in range(1, 8):  # 5 to 11 Oct, 20:00-22:00 IST
        start = datetime(2026, 10, 4 + i, tzinfo=UTC) + timedelta(hours=20) - SHIFT
        for m in range(120):
            s.add(Observation(video_id=v.id, channel_id=c.id, observed_at=start + timedelta(minutes=m), view_count=1, concurrent_viewers=level, is_live=True, classification="LIVE", source="test"))


AGE = {"13-17": 5, "18-24": 20, "25-34": 35, "35-44": 25, "45-54": 10, "55-64": 4, "65+": 1}


def test_profile_keeps_its_source_and_checks_every_figure():
    s, _ = make()
    c = chan(s, "a", "Alpha")
    out = audience.set_profile(s, channel_id=c.id, source="channel_media_kit", source_note="Media kit PDF sent by the channel on 2 Oct", as_of="2026-10-01", age=AGE,
                               gender={"male": 70, "female": 30}, states={"Uttar Pradesh": 22, "Bihar": 14, "Jharkhand": 6}, countries={"India": 93, "Nepal": 2}, by="admin@x.com")
    assert out["source_label"].startswith("Channel's media kit") and out["states"]["Bihar"] == 14 and out["updated_by"] == "admin@x.com"
    base = dict(channel_id=c.id, source="channel_media_kit", source_note="note", as_of="2026-10-01", age=AGE, gender=None, states=None, countries=None, by="a")
    for bad in (dict(source="guess"), dict(source_note=" "), dict(as_of="2999-01-01"), dict(as_of="soon"), dict(age={"13-17": 60, "18-24": 60}), dict(age={"10-12": 100}), dict(age={"18-24": 20}),
                dict(states={"Atlantis": 5}), dict(states={"Bihar": 70, "Jharkhand": 40}), dict(states={"Bihar": "many"}), dict(age=None, gender=None, states=None, countries=None)):
        with pytest.raises(ValueError):
            audience.set_profile(s, **{**base, **bad})
    with pytest.raises(LookupError):
        audience.set_profile(s, **{**base, "channel_id": 999})
    assert s.query(AudienceProfile).count() == 1
    assert audience.remove_profile(s, c.id)["removed"] and s.query(AudienceProfile).count() == 0
    with pytest.raises(LookupError):
        audience.remove_profile(s, c.id)


def test_overview_says_not_known_for_channels_without_a_profile():
    s, _ = make()
    a, b = chan(s, "a", "Alpha"), chan(s, "b", "Beta")
    audience.set_profile(s, channel_id=a.id, source="youtube_analytics", source_note="Studio screenshot from the channel", as_of="2026-10-01", age=AGE, gender=None, states=None, countries=None, by="a")
    out = audience.overview(s)
    rows = {r["name"]: r for r in out["channels"]}
    assert rows["Alpha"]["profile"]["age"]["25-34"] == 35 and rows["Beta"]["profile"] is None
    assert out["with_profile"] == 1 and out["total"] == 2 and "does not publish" in out["note"]


def test_match_multiplies_the_parts_it_has_and_names_what_is_missing():
    p = {"age": AGE, "gender": {"male": 70, "female": 30}, "states": {"Bihar": 20, "Jharkhand": 10}, "as_of": "2026-10-01", "source": "channel_media_kit"}
    m = audience.match(p, ages=["25-34", "35-44"], states=["Bihar", "Jharkhand"], gender="male")
    assert m["share"] == pytest.approx(0.60 * 0.30 * 0.70, abs=1e-4) and m["used"] == ["age", "states", "gender"] and m["missing"] == []
    partial = audience.match({**p, "states": {}}, ages=["25-34"], states=["Bihar"], gender="")
    assert partial["share"] == pytest.approx(0.35) and partial["missing"] == ["states"]
    assert audience.match(None, ages=["25-34"], states=[], gender="") is None
    assert audience.match({**p, "age": {}, "states": {}, "gender": {}}, ages=["25-34"], states=[], gender="") is None


def test_planner_with_a_target_ranks_by_the_matching_audience_and_never_buys_a_channel_with_no_audience_data():
    s, _ = make()
    a, b, c = chan(s, "a", "BigButWrongAudience"), chan(s, "b", "SmallButRight"), chan(s, "c", "Unknown")
    live(s, a, "alive", 10_000)
    live(s, b, "blive", 4_000)
    live(s, c, "clive", 20_000)
    for ch, ages in ((a, {"13-17": 40, "18-24": 40, "25-34": 10, "35-44": 5, "45-54": 3, "55-64": 1, "65+": 1}), (b, {"13-17": 2, "18-24": 8, "25-34": 45, "35-44": 35, "45-54": 7, "55-64": 2, "65+": 1})):
        audience.set_profile(s, channel_id=ch.id, source="channel_media_kit", source_note="kit", as_of="2026-10-01", age=ages, gender=None, states=None, countries=None, by="a")
    s.commit()
    plain = media_plan(s, start_hour=20, end_hour=22, days=7, rates={a.id: 10_000, b.id: 10_000, c.id: 10_000}, budget=60_000, max_share=1.0, now=NOW)
    assert plain["channels"][0]["name"] == "Unknown" and not plain["target"]["active"]
    targeted = media_plan(s, start_hour=20, end_hour=22, days=7, rates={a.id: 10_000, b.id: 10_000, c.id: 10_000}, budget=60_000, max_share=1.0, profiles=audience.profiles(s),
                          target={"ages": ["25-34", "35-44"]}, now=NOW)
    rows = {r["name"]: r for r in targeted["channels"]}
    assert rows["SmallButRight"]["matched_audience"] == pytest.approx(4_000 * 0.80, abs=5) and rows["BigButWrongAudience"]["matched_audience"] == pytest.approx(10_000 * 0.15, abs=5)
    assert rows["Unknown"]["matched_audience"] is None and not rows["Unknown"]["audience_known"]
    assert rows["SmallButRight"]["cost_per_1000_matched"] < rows["BigButWrongAudience"]["cost_per_1000_matched"]
    assert rows["SmallButRight"]["value_index"] > rows["BigButWrongAudience"]["value_index"]
    plan = targeted["plan"]
    assert "Unknown" not in [line["name"] for line in plan["lines"]] and plan["skipped_no_audience_data"] == ["Unknown"] and plan["counts_matched_audience_only"]
    assert {line["name"] for line in plan["lines"]} <= {"SmallButRight", "BigButWrongAudience"} and plan["lines"][0]["name"] == "SmallButRight"
    assert targeted["target"]["channels_with_audience_data"] == 2 and "no audience data" in targeted["method"]
    for bad in ({"ages": ["0-5"]}, {"states": ["Narnia"]}, {"gender": "robot"}):
        with pytest.raises(ValueError):
            media_plan(s, start_hour=20, end_hour=22, days=7, target=bad, now=NOW)


def test_the_pdf_is_branded_unreadable_by_machines_and_only_printable():
    pytest.importorskip("fitz")
    pytest.importorskip("reportlab")
    from api.report_pdf import _mupdf
    fitz = _mupdf()
    from api.report_pdf import logo_png, report_pdf
    s, _ = make()
    a = chan(s, "a", "Alpha")
    live(s, a, "alive", 10_000)
    s.commit()
    report = build_report(s, start_date="2026-10-05", end_date="2026-10-11", start_hour=20, end_hour=22, scope="live", now=NOW)
    report["prepared_for"] = "buyer@agency.com (Agency)"
    protected = report_pdf(report)
    plain = report_pdf(report, protect=False)
    # the plain version has real text; the protected one has none to lift
    plain_doc, doc = fitz.open(stream=plain, filetype="pdf"), fitz.open(stream=protected, filetype="pdf")
    assert "Alpha" in plain_doc[0].get_text() and "stataxis" in plain_doc[0].get_text().lower()
    assert "Downloaded " in plain_doc[0].get_text() and " IST" in plain_doc[0].get_text()   # every report says when it was downloaded
    assert b"/Encrypt" in protected and b"/Encrypt" not in plain and doc.authenticate("") > 0
    assert all(page.get_text().strip() == "" for page in doc) and all(page.get_images() for page in doc)
    assert doc.permissions & fitz.PDF_PERM_PRINT and not doc.permissions & fitz.PDF_PERM_COPY and not doc.permissions & fitz.PDF_PERM_MODIFY
    assert doc.metadata["author"] == "STATAXIS" and "Alpha" not in (doc.metadata.get("title") or "")
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(1, 1))
    assert pix.width > 400 and pix.height > 500
    assert logo_png()[:8] == b"\x89PNG\r\n\x1a\n" and len(protected) > 20_000
    # the page is not blank: the header band is dark navy at the top and there is ink on the page
    assert pix.pixel(10, 5)[:3] != (255, 255, 255) and any(pix.pixel(x, y)[:3] != (255, 255, 255) for x in range(60, 300, 20) for y in range(120, 300, 20))


def test_audience_route_is_for_analyst_and_above_and_the_admin_route_sets_a_profile():
    s, engine = make()
    c = chan(s, "a", "Alpha")
    for uid, email, plan, admin in ((1, "idea@x.com", "sx_idea", False), (2, "an@x.com", "sx_analyst", False), (3, "boss@x.com", "sx_enterprise", True)):
        s.add(User(id=uid, email=email, password_hash="x", plan=plan, is_admin=admin, active=True, approval_status="approved"))
    s.commit()
    cid = c.id
    market = market_application(lambda: Session(engine))
    admin_app = admin_application(lambda: Session(engine))

    def call(app, method, path, uid, email, plan, admin=False, body=None):
        raw = json.dumps(body).encode() if body is not None else b""
        out = {}
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)),
                   "HTTP_AUTHORIZATION": "Bearer " + issue_token(AuthIdentity(uid, email, plan, admin))}
        res = app(environ, lambda status, headers: out.update(status=status))
        return int(out["status"].split()[0]), json.loads(res[0])

    assert call(market, "GET", "/api/v1/market/audience", 1, "idea@x.com", "sx_idea")[0] == 403
    status, body = call(market, "GET", "/api/v1/market/audience", 2, "an@x.com", "sx_analyst")
    assert status == 200 and body["with_profile"] == 0 and body["channels"][0]["profile"] is None
    payload = {"channel_id": cid, "source": "youtube_analytics", "source_note": "Studio screenshot received from the channel", "as_of": "2026-10-01", "age": AGE, "states": {"Bihar": 15}}
    assert call(admin_app, "POST", "/api/v1/admin/audience/set", 2, "an@x.com", "sx_analyst", False, payload)[0] == 403
    status, body = call(admin_app, "POST", "/api/v1/admin/audience/set", 3, "boss@x.com", "sx_enterprise", True, payload)
    assert status == 200 and body["states"] == {"Bihar": 15.0}
    assert call(admin_app, "POST", "/api/v1/admin/audience/set", 3, "boss@x.com", "sx_enterprise", True, {**payload, "states": {"Narnia": 5}})[0] == 400
    status, body = call(market, "GET", "/api/v1/market/audience", 2, "an@x.com", "sx_analyst")
    assert body["with_profile"] == 1 and body["channels"][0]["profile"]["as_of"] == "2026-10-01"
    assert call(admin_app, "POST", "/api/v1/admin/audience/remove", 3, "boss@x.com", "sx_enterprise", True, {"channel_id": cid})[0] == 200
