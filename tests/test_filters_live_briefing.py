"""The common filters (category, language, time, place, age group, individual channel), the live event compare for up to 30 channels, and the role-based briefing."""
import io
import re
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import audience
from api.auth import AuthIdentity, issue_token
from api.findings import PERSONAS, briefing, briefing_as_report
from api.live_event import live_event_compare
from api.market_http import market_application
from api.market_tools import prime_time, weekly_views
from api.report_builder import build_report
from collector.storage import Base, Channel, Observation, User, Video

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
SHIFT = timedelta(hours=5, minutes=30)


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")


def make():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return Session(engine), engine


def chan(s, key, name, segment="news", language="Hindi"):
    c = Channel(youtube_channel_id=key, name=name, network="n", language=language, region="India", segment=segment)
    s.add(c)
    s.flush()
    return c


def upload(s, c, key, published, views, likes=0, cls="REGULAR_VIDEO", topic="Politics"):
    v = Video(youtube_video_id=key, channel_id=c.id, title=key, topic=topic, published_at=published.strftime("%Y-%m-%dT%H:%M:%SZ"))
    s.add(v)
    s.flush()
    s.add(Observation(video_id=v.id, channel_id=c.id, observed_at=NOW - timedelta(hours=1), view_count=views, like_count=likes, comment_count=0, concurrent_viewers=None, is_live=False, classification=cls, source="test"))


def evening(s, c, key, level, days=range(1, 8), title=None):
    v = Video(youtube_video_id=key, channel_id=c.id, title=title or key, topic="Politics", live_started_at=NOW - timedelta(days=60))
    s.add(v)
    s.flush()
    for i in days:
        start = datetime(2026, 10, 4 + i, tzinfo=UTC) + timedelta(hours=20) - SHIFT
        for m in range(120):
            s.add(Observation(video_id=v.id, channel_id=c.id, observed_at=start + timedelta(minutes=m), view_count=1, concurrent_viewers=level, is_live=True, classification="LIVE", source="test"))


AGE_YOUNG = {"13-17": 10, "18-24": 40, "25-34": 30, "35-44": 12, "45-54": 5, "55-64": 2, "65+": 1}
AGE_OLD = {"13-17": 1, "18-24": 4, "25-34": 10, "35-44": 20, "45-54": 30, "55-64": 25, "65+": 10}


# ------------------------------------------------------------------------------------ filters
def test_an_individual_channel_or_a_few_narrow_every_report():
    s, _ = make()
    a, b, c = chan(s, "a", "Alpha"), chan(s, "b", "Beta"), chan(s, "c", "Gamma")
    for ch, views in ((a, 900_000), (b, 600_000), (c, 100_000)):
        upload(s, ch, f"{ch.name}1", datetime(2026, 10, 8, 10, tzinfo=UTC), views)
    for ch, level in ((a, 9000), (b, 6000), (c, 1000)):
        evening(s, ch, f"{ch.name}live", level)
    s.commit()
    w = weekly_views(s, start_date="2026-10-05", end_date="2026-10-11", channel_ids=[b.id], now=NOW)
    assert [x["name"] for g in w["groups"] for x in g["channels"]] == ["Beta"] and w["filters"]["channel_ids"] == [b.id]
    both = weekly_views(s, start_date="2026-10-05", end_date="2026-10-11", channel_ids=[a.id, c.id], now=NOW)
    assert [x["name"] for x in both["groups"][0]["channels"]] == ["Alpha", "Gamma"]
    pt = prime_time(s, start_date="2026-10-05", end_date="2026-10-11", channel_ids=[c.id], now=NOW)
    shown = [r["name"] for sl in pt["slots"] for r in sl["channels"]]
    assert shown and set(shown) == {"Gamma"}                                                    # only the channel asked for, in every slot it was live
    rep = build_report(s, start_date="2026-10-05", end_date="2026-10-11", start_hour=20, end_hour=22, scope="live", channel_ids=[a.id], now=NOW)
    assert [r["name"] for r in rep["rows"]] == ["Alpha"]
    vrep = build_report(s, start_date="2026-10-08", end_date="2026-10-08", start_hour=0, end_hour=24, scope="video", channel_ids=[a.id], now=NOW)
    assert all(r["name"] == "Alpha" for r in vrep["rows"])


def test_place_and_age_group_re_rank_by_the_matching_audience_and_mark_unknown_channels():
    s, _ = make()
    young, old, unknown = chan(s, "y", "YoungSkew"), chan(s, "o", "OldSkew"), chan(s, "u", "NoData")
    for ch, views in ((young, 500_000), (old, 800_000), (unknown, 1_000_000)):
        upload(s, ch, f"{ch.name}1", datetime(2026, 10, 8, 10, tzinfo=UTC), views)
    audience.set_profile(s, channel_id=young.id, source="channel_media_kit", source_note="kit", as_of="2026-10-01", age=AGE_YOUNG, gender=None, states={"Bihar": 30, "Jharkhand": 10}, countries=None, by="a")
    audience.set_profile(s, channel_id=old.id, source="channel_media_kit", source_note="kit", as_of="2026-10-01", age=AGE_OLD, gender=None, states={"Bihar": 5, "Jharkhand": 2}, countries=None, by="a")
    s.commit()
    target = audience.parse_target("18-24,25-34", "Bihar,Jharkhand", "")
    assert target["active"] and target["ages"] == ["18-24", "25-34"] and target["states"] == ["Bihar", "Jharkhand"]
    w = weekly_views(s, start_date="2026-10-05", end_date="2026-10-11", target=target, profiles=audience.profiles(s), now=NOW)
    rows = w["groups"][0]["channels"]
    assert [r["name"] for r in rows][:2] == ["YoungSkew", "OldSkew"]                       # the biggest channel is not the best match
    assert rows[0]["matched_views"] == pytest.approx(500_000 * 0.70 * 0.40, rel=0.01) and rows[2]["name"] == "NoData" and rows[2]["audience_match"] is None and rows[2]["matched_views"] is None
    only = weekly_views(s, start_date="2026-10-05", end_date="2026-10-11", target=target, profiles=audience.profiles(s), known_only=True, now=NOW)
    assert [r["name"] for r in only["groups"][0]["channels"]] == ["YoungSkew", "OldSkew"] and "no audience data" in w["method"]
    plain = weekly_views(s, start_date="2026-10-05", end_date="2026-10-11", now=NOW)
    assert plain["groups"][0]["channels"][0]["name"] == "NoData" and "matched_views" not in plain["groups"][0]["channels"][0]
    for bad in (("0-5", "", ""), ("", "Narnia", ""), ("", "", "robot")):
        with pytest.raises(ValueError):
            audience.parse_target(*bad)
    assert audience.parse_target()["active"] is False


# ------------------------------------------------------------------------------------ live event compare
def stream(s, c, key, title, series, started=None):
    v = Video(youtube_video_id=key, channel_id=c.id, title=title, topic="Politics", live_started_at=started or NOW - timedelta(hours=2))
    s.add(v)
    s.flush()
    for minutes_ago, viewers in series:
        s.add(Observation(video_id=v.id, channel_id=c.id, observed_at=NOW - timedelta(minutes=minutes_ago), view_count=1, concurrent_viewers=viewers, is_live=True, classification="LIVE", source="test"))


def test_live_event_compare_finds_the_channels_covering_the_event_and_reads_the_tone():
    s, _ = make()
    a, b, c, d = chan(s, "a", "Alpha"), chan(s, "b", "Beta"), chan(s, "c", "Gamma"), chan(s, "d", "Delta")
    ramp = [(m, 20_000 - m * 100) for m in range(60, -1, -1)]               # a steady climb to 20,000 now
    stream(s, a, "a1", "Budget 2027 live: markets surge to record gains", ramp)
    stream(s, b, "b1", "Union Budget 2027 special: crisis fears and losses", [(m, 8_000) for m in range(60, -1, -1)])
    stream(s, c, "c1", "Cricket live: India vs Australia", [(m, 50_000) for m in range(60, -1, -1)])   # live but not about the budget
    stream(s, d, "d1", "Budget day studio", [(m, 3_000) for m in range(60, 20, -1)])                    # went off air 20 minutes ago
    s.commit()
    out = live_event_compare(s, terms=["budget"], now=NOW)
    names = [r["name"] for r in out["channels"]]
    assert names == ["Alpha", "Beta"] and out["summary"]["channels_live"] == 2 and out["summary"]["total_live_now"] == 28_000
    alpha, beta = out["channels"]
    assert alpha["live_now"] == 20_000 and alpha["share_percent"] == pytest.approx(71.4, abs=0.1) and alpha["change_5m_percent"] == pytest.approx(2.6, abs=0.2)
    assert alpha["peak"] == 20_000 and alpha["tone"]["label"] == "positive" and beta["tone"]["label"] == "negative" and alpha["matches_event"] is True
    assert len(alpha["series"]) == 31 and alpha["series"][-1] == 20_000 and alpha["live_for_minutes"] == 120
    assert out["summary"]["tone_mix"] == {"positive": 1, "negative": 1, "mixed/neutral": 0} and "indicative" in out["method"] and out["summary"]["leader"] == "Alpha"
    picked = live_event_compare(s, channel_ids=[a.id, c.id, d.id], now=NOW)
    assert [r["name"] for r in picked["channels"]] == ["Gamma", "Alpha"] and picked["not_live"] == ["Delta"]
    assert live_event_compare(s, terms=["election"], now=NOW)["note"].startswith("No channel is live now")
    everyone = live_event_compare(s, now=NOW)
    assert [r["name"] for r in everyone["channels"]] == ["Gamma", "Alpha", "Beta"]


def test_live_event_compare_takes_up_to_thirty_channels_and_checks_its_inputs():
    s, _ = make()
    ids = []
    for i in range(32):
        c = chan(s, f"c{i}", f"Chan{i}")
        stream(s, c, f"v{i}", "Live coverage", [(m, 1_000 + i * 100) for m in range(30, -1, -1)])
        ids.append(c.id)
    s.commit()
    assert len(live_event_compare(s, now=NOW)["channels"]) == 30
    assert len(live_event_compare(s, channel_ids=ids[:30], now=NOW)["channels"]) == 30
    with pytest.raises(ValueError, match="at most 30"):
        live_event_compare(s, channel_ids=ids, now=NOW)
    with pytest.raises(ValueError):
        live_event_compare(s, minutes=5, now=NOW)


# ------------------------------------------------------------------------------------ briefing
def seed_market(s):
    chans = [chan(s, f"n{i}", name) for i, name in enumerate(["Alpha", "Beta", "Gamma", "Delta"])]
    for i, ch in enumerate(chans):
        for k in range(6):
            upload(s, ch, f"{ch.name}c{k}", datetime(2026, 10, 6 + (k % 5), 9, tzinfo=UTC), (4 - i) * 100_000, likes=(4 - i) * 3_000, cls="SHORT" if k % 2 else "REGULAR_VIDEO", topic="Politics" if k % 3 else "Sports")
            upload(s, ch, f"{ch.name}p{k}", datetime(2026, 9, 28, 9, tzinfo=UTC) + timedelta(days=k % 5), (1 + i) * 80_000, likes=2_000)   # the week before
        evening(s, ch, f"{ch.name}live", 10_000 - i * 2_500)
    s.commit()
    return chans


def test_each_role_gets_findings_with_evidence_and_what_to_do_about_them():
    s, _ = make()
    seed_market(s)
    out = {p: briefing(s, persona=p, days=7, now=NOW) for p in PERSONAS}
    for p, b in out.items():
        assert b["persona"] == p and b["findings"] and b["kpis"] and b["recommended"] and len(b["process"]) == 8
        for f in b["findings"]:
            assert f["headline"] and f["so_what"] and f["evidence"] and f["confidence"] in {"high", "medium", "low"} and f["tool"]
    buyer = {f["id"]: f for f in out["buyer"]["findings"]}
    assert "prime-leader" in buyer and buyer["prime-leader"]["evidence"]["leader"] == "Alpha" and "media planner" in buyer["prime-leader"]["so_what"]
    assert out["buyer"]["findings"][0]["id"] == "prime-leader"                                # the buyer's most useful finding comes first
    assert any(f["id"].startswith("share-") for f in out["media"]["findings"])
    share = next(f for f in out["media"]["findings"] if f["id"].startswith("share-"))
    assert share["evidence"]["leader"] == "Alpha" and share["evidence"]["total_views"] > 0
    assert {f["so_what"] for f in out["media"]["findings"]} != {f["so_what"] for f in out["buyer"]["findings"]}   # same facts, different advice
    narrow = briefing(s, persona="buyer", days=7, channel_ids=[1], now=NOW)
    assert all(f["id"] != "share-Hindi News" for f in narrow["findings"])                   # a single channel has no market to lead
    with pytest.raises(ValueError):
        briefing(s, persona="alien", now=NOW)
    with pytest.raises(ValueError):
        briefing(s, persona="buyer", days=1, now=NOW)


def test_a_briefing_with_no_data_says_so_instead_of_inventing_findings():
    s, _ = make()
    b = briefing(s, persona="media", now=NOW)
    assert b["findings"] == [] or all(f["id"].startswith("authenticity") for f in b["findings"])
    assert b["note"] is None or "not enough" in b["note"]


def test_the_briefing_turns_into_a_branded_pdf_with_the_findings_first():
    pytest.importorskip("fitz")
    pytest.importorskip("reportlab")
    from api.report_pdf import _mupdf, filename, report_pdf
    s, _ = make()
    seed_market(s)
    b = briefing(s, persona="buyer", days=7, now=NOW)
    rep = briefing_as_report(b)
    rep["prepared_for"] = "buyer@agency.com"
    assert re.fullmatch(rf"stataxis-briefing-buyer-{b['window']['from']}-to-{b['window']['to']}-downloaded-\d{{8}}-\d{{4}}\.pdf", filename(rep))
    plain = _mupdf().open(stream=report_pdf(rep, protect=False), filetype="pdf")
    text = " ".join(p.get_text() for p in plain)
    assert "briefing for media buyer" in text.lower() and b["findings"][0]["headline"][:30] in text and "For you:" in text and "Where to look next" in text
    protected = _mupdf().open(stream=report_pdf(rep), filetype="pdf")
    assert all(p.get_text().strip() == "" for p in protected)


def test_http_filters_briefing_live_event_and_upgrade_requests():
    s, engine = make()
    seed_market(s)
    for uid, email, plan, admin in ((1, "free@x.com", "sx_free", False), (2, "idea@x.com", "sx_idea", False), (3, "intel@x.com", "sx_intelligence", False)):
        s.add(User(id=uid, email=email, password_hash="x", plan=plan, is_admin=admin, active=True, approval_status="approved", organization="Org"))
    s.commit()
    app = market_application(lambda: Session(engine))

    def call(method, path, uid, email, plan, query="", body=None):
        raw = json.dumps(body).encode() if body is not None else b""
        out = {}
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)),
                   "HTTP_AUTHORIZATION": "Bearer " + issue_token(AuthIdentity(uid, email, plan, False))}
        res = app(environ, lambda status, headers: out.update(status=status))
        return int(out["status"].split()[0]), json.loads(res[0]) if res[0][:1] in (b"{", b"[") else res[0]

    status, free_brief = call("GET", "/api/v1/market/briefing", 1, "free@x.com", "sx_free", "persona=buyer")
    assert status == 200 and free_brief["locked"] and len(free_brief["findings"]) <= 3 and all(f["so_what"] is None and f["evidence"] == {} for f in free_brief["findings"]) and "SX Idea" in free_brief["upgrade"]
    status, full = call("GET", "/api/v1/market/briefing", 2, "idea@x.com", "sx_idea", "persona=buyer&channels=1,2")
    assert status == 200 and not full.get("locked") and full["filters"]["channel_ids"] == [1, 2]
    assert call("GET", "/api/v1/market/briefing", 2, "idea@x.com", "sx_idea", "persona=wizard")[0] == 400
    assert call("GET", "/api/v1/market/live-event", 2, "idea@x.com", "sx_idea")[0] == 403           # needs SX Intelligence
    status, live = call("GET", "/api/v1/market/live-event", 3, "intel@x.com", "sx_intelligence", "terms=anything&minutes=30")
    assert status == 200 and live["channels"] == []
    assert call("GET", "/api/v1/market/live-event", 3, "intel@x.com", "sx_intelligence", "channels=1,2,abc")[0] == 400
    status, w = call("GET", "/api/v1/market/weekly", 2, "idea@x.com", "sx_idea", "from=2026-10-05&to=2026-10-11&channels=2&ages=18-24&states=Bihar")
    assert status == 200 and w["target"]["active"] and w["groups"][0]["channels"][0]["audience_match"] is None
    assert call("GET", "/api/v1/market/weekly", 2, "idea@x.com", "sx_idea", "ages=99-100")[0] == 400
    status, body = call("POST", "/api/v1/market/upgrade-request", 2, "idea@x.com", "sx_idea", body={"plan": "sx_pro"})
    assert status == 200 and body["requested_plan"] == "sx_pro"
    assert call("POST", "/api/v1/market/upgrade-request", 2, "idea@x.com", "sx_idea", body={"plan": "sx_free"})[0] == 400
    with Session(engine) as check:
        user = check.get(User, 2)
        assert user.requested_plan == "sx_pro" and user.plan == "sx_idea"                      # asking does not grant
