"""Report builder with PDF, the creator index, package access and the admin user tools, on invented data in a scratch database."""
import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import feature_access, user_admin
from api.admin_http import admin_application
from api.auth import AuthIdentity, hash_password, issue_token, verify_password
from api.report_builder import GENRES, build_report
from api.creator_index import creator_index
from collector.storage import Base, Channel, ChannelStats, Observation, User, Video

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
IST_SHIFT = timedelta(hours=5, minutes=30)


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")


def make_session():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return Session(engine), engine


def channel(s, key, name, segment="news", language="Hindi"):
    c = Channel(youtube_channel_id=key, name=name, network="n", language=language, region="India", segment=segment)
    s.add(c)
    s.flush()
    return c


def ist(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC) - IST_SHIFT


def live(s, ch, key, day, h0, h1, level, topic="Politics", primary=True):
    started = ist(day, h0) - (timedelta(days=60) if primary else timedelta(minutes=30))
    v = s.query(Video).filter_by(youtube_video_id=key).one_or_none() or Video(youtube_video_id=key, channel_id=ch.id, title=key, topic=topic, live_started_at=started)
    if v.id is None:
        s.add(v)
        s.flush()
    for m in range((h1 - h0) * 60):
        s.add(Observation(video_id=v.id, channel_id=ch.id, observed_at=ist(day, h0) + timedelta(minutes=m), view_count=1, concurrent_viewers=level, is_live=True, classification="LIVE", source="test"))


def test_live_report_follows_the_hours_the_feed_and_the_genre():
    s, _ = make_session()
    a, b = channel(s, "a", "Alpha"), channel(s, "b", "Beta")
    for i in (9, 10, 11):
        d = datetime(2026, 10, i).date()
        live(s, a, "a-main", d, 9, 12, 10_000, topic="Politics")                    # long-running main stream
        live(s, a, "a-event", d, 9, 12, 2_000, topic="Sports", primary=False)       # an event stream next to it
        live(s, a, "a-main", d, 15, 16, 99_000, topic="Politics")                   # outside the chosen hours: must not count
        live(s, b, "b-main", d, 9, 12, 4_000, topic="Sports")
    s.commit()
    allf = build_report(s, start_date="2026-10-09", end_date="2026-10-11", start_hour=9, end_hour=12, feed="all", scope="live", now=NOW)
    rows = {r["name"]: r for r in allf["rows"]}
    assert rows["Alpha"]["average"] == 12_000 and rows["Beta"]["average"] == 4_000 and rows["Alpha"]["days_seen"] == 3 and rows["Alpha"]["rank"] == 1
    assert rows["Alpha"]["peak"] == 12_000
    primary = {r["name"]: r for r in build_report(s, start_date="2026-10-09", end_date="2026-10-11", start_hour=9, end_hour=12, feed="primary", scope="live", now=NOW)["rows"]}
    assert primary["Alpha"]["average"] == 10_000
    secondary = {r["name"]: r for r in build_report(s, start_date="2026-10-09", end_date="2026-10-11", start_hour=9, end_hour=12, feed="secondary", scope="live", now=NOW)["rows"]}
    assert secondary["Alpha"]["average"] == 2_000
    sports = build_report(s, start_date="2026-10-09", end_date="2026-10-11", start_hour=9, end_hour=12, feed="all", scope="live", genre="Sports", now=NOW)
    assert {r["name"]: r["average"] for r in sports["rows"]} == {"Alpha": 2_000, "Beta": 4_000}
    split = build_report(s, start_date="2026-10-09", end_date="2026-10-11", start_hour=9, end_hour=12, feed="all", scope="live", by_genre=True, now=NOW)
    assert {g["genre"] for g in split["by_genre"]} == {"Politics", "Sports"}


def test_views_report_counts_gains_inside_the_hours_for_videos_or_shorts_and_leaves_out_unmeasured_ones():
    s, _ = make_session()
    a = channel(s, "a", "Alpha")
    day = datetime(2026, 10, 10).date()
    s0, e0 = ist(day, 9), ist(day, 12)

    def vid(key, cls, topic, published, series):
        v = Video(youtube_video_id=key, channel_id=a.id, title=key, topic=topic, published_at=published.strftime("%Y-%m-%dT%H:%M:%SZ"))
        s.add(v)
        s.flush()
        for when, views in series:
            s.add(Observation(video_id=v.id, channel_id=a.id, observed_at=when, view_count=views, like_count=0, comment_count=0, concurrent_viewers=None, is_live=False, classification=cls, source="test"))

    old = s0 - timedelta(days=3)
    vid("v1", "REGULAR_VIDEO", "Politics", old, [(s0 - timedelta(minutes=20), 1000), (e0 - timedelta(minutes=10), 6000)])         # +5000 in the window
    vid("sh", "SHORT", "Entertainment", old, [(s0 - timedelta(minutes=20), 100), (e0 - timedelta(minutes=10), 900)])              # +800
    vid("new", "REGULAR_VIDEO", "Sports", s0 + timedelta(hours=1), [(e0 - timedelta(minutes=5), 700)])                             # uploaded inside the window: starts from zero
    vid("gap", "REGULAR_VIDEO", "Politics", old, [(s0 - timedelta(hours=10), 50), (e0 - timedelta(minutes=10), 5000)])            # not measured near the start: left out
    s.commit()
    vids = build_report(s, start_date="2026-10-10", end_date="2026-10-10", start_hour=9, end_hour=12, scope="video", by_genre=True, now=NOW)
    assert vids["kind"] == "views" and vids["rows"][0]["views"] == 5_700 and vids["rows"][0]["uploads"] == 1
    assert vids["coverage"] == {"videos_matching": 3, "videos_measured_at_both_ends": 2, "videos_left_out": 1, "percent_measured": 66.7}
    assert {g["genre"]: g["views"] for g in vids["by_genre"]} == {"Politics": 5_000, "Sports": 700}
    shorts = build_report(s, start_date="2026-10-10", end_date="2026-10-10", start_hour=9, end_hour=12, scope="shorts", now=NOW)
    assert shorts["rows"][0]["views"] == 800
    politics = build_report(s, start_date="2026-10-10", end_date="2026-10-10", start_hour=9, end_hour=12, scope="video", genre="Politics", now=NOW)
    assert politics["rows"][0]["views"] == 5_000


def test_report_builder_checks_its_inputs():
    s, _ = make_session()
    base = dict(start_date="2026-10-09", end_date="2026-10-10", now=NOW)
    for bad in (dict(feed="x"), dict(scope="tv"), dict(genre="Cooking"), dict(start_hour=12, end_hour=9), dict(start_hour=0, end_hour=30), dict(start_date="2026-09-01", end_date="2026-10-10", scope="video")):
        with pytest.raises(ValueError):
            build_report(s, **{**base, **bad})
    assert "Politics" in GENRES and "Other" in GENRES


def test_pdf_is_a_real_pdf_with_the_filters_the_table_and_the_method():
    pytest.importorskip("reportlab")
    from api.report_pdf import filename, report_pdf
    s, _ = make_session()
    a = channel(s, "a", "Alpha")
    live(s, a, "a-main", datetime(2026, 10, 10).date(), 9, 12, 10_000)
    s.commit()
    report = build_report(s, start_date="2026-10-10", end_date="2026-10-10", start_hour=9, end_hour=12, scope="live", by_genre=True, now=NOW)
    pdf = report_pdf(report)
    assert pdf[:5] == b"%PDF-" and len(pdf) > 2000
    assert filename(report) == "stataxis-live-2026-10-10-to-2026-10-10-09-12.pdf"
    empty = report_pdf(build_report(s, start_date="2026-10-05", end_date="2026-10-05", scope="live", now=NOW))
    assert empty[:5] == b"%PDF-"


def test_stx_c_scores_creators_who_publish_videos_and_shorts_and_is_honest_about_thin_data():
    s, _ = make_session()
    specs = [("Steady", 100_000, 40_000, 0.05), ("Hit", 100_000, 90_000, 0.04), ("Quiet", 100_000, 5_000, 0.01), ("Mid", 80_000, 20_000, 0.03), ("Small", 20_000, 8_000, 0.045), ("New", 50_000, 10_000, 0.03)]
    for i, (name, subs, views, like_rate) in enumerate(specs):
        c = channel(s, f"c{i}", name, segment="creator")
        s.add(ChannelStats(channel_id=c.id, observed_at=NOW - timedelta(days=8), subscribers=subs, total_views=1))
        s.add(ChannelStats(channel_id=c.id, observed_at=NOW - timedelta(hours=1), subscribers=int(subs * (1.05 if name == "Steady" else 1.0)), total_views=1))
        n = 3 if name == "New" else 12
        for k in range(n):
            published = NOW - timedelta(days=k * 2 + 3)
            v = int(views * ((1.6 if k % 4 == 0 else 0.7) if name == "Hit" else (1.0 + 0.05 * (k % 3))))
            short = k % 3 == 0
            vv = Video(youtube_video_id=f"{name}{k}", channel_id=c.id, title=f"{name}{k}", topic="Other", published_at=published.strftime("%Y-%m-%dT%H:%M:%SZ"))
            s.add(vv)
            s.flush()
            s.add(Observation(video_id=vv.id, channel_id=c.id, observed_at=NOW - timedelta(hours=1), view_count=v, like_count=int(v * like_rate), comment_count=v // 200, concurrent_viewers=None, is_live=False,
                              classification="SHORT" if short else "REGULAR_VIDEO", source="test"))
            if k >= 5:
                s.add(Observation(video_id=vv.id, channel_id=c.id, observed_at=NOW - timedelta(days=5), view_count=int(v * 0.8), like_count=1, comment_count=0, concurrent_viewers=None, is_live=False,
                                  classification="SHORT" if short else "REGULAR_VIDEO", source="test"))
    s.commit()
    out = creator_index(s, segment="creator", days=30, now=NOW, with_authenticity=False)
    rows = {r["name"]: r for r in out["channels"]}
    assert out["index_name"] == "IFX Score" and out["tagline"] == "Impact · Followership · eXposure" and set(out["pillar_names"]) == {"impact", "followership", "exposure"} and set(rows) == {"Steady", "Hit", "Quiet", "Mid", "Small", "New"}
    assert rows["Steady"]["index_score"] > rows["Quiet"]["index_score"]
    assert rows["New"]["preliminary"] and rows["New"]["profile"].startswith("Emerging")      # three uploads: not trusted
    assert abs(rows["New"]["index_score"] - 50) < abs(rows["New"]["raw_score"] - 50) + 0.01           # pulled toward 50
    assert rows["Hit"]["parts"]["steadiness"] < rows["Steady"]["parts"]["steadiness"]            # uneven results score lower on steadiness
    steady = rows["Steady"]
    assert set(steady["pillars"]) == {"impact", "followership", "exposure"} and all(0 <= v <= 100 for v in steady["pillars"].values() if v is not None)
    assert steady["uploads_shorts"] > 0 and rows["Steady"]["uploads_video"] > 0 and rows["Steady"]["best_format"] in {"Shorts", "Videos"}
    assert all(r["rank"] for r in out["channels"] if r["index_score"] is not None) and "Live streams are excluded" in out["method"] and out["not_measured"] and abs(sum(out["pillar_weights"].values()) - 1) < 0.001
    with pytest.raises(ValueError):
        creator_index(s, days=3)


def test_stx_c_holds_back_a_score_an_admin_confirmed_and_marks_high_risk(monkeypatch):
    s, _ = make_session()
    for i in range(6):
        c = channel(s, f"x{i}", f"C{i}", segment="journalist")
        s.add(ChannelStats(channel_id=c.id, observed_at=NOW - timedelta(hours=1), subscribers=50_000, total_views=1))
        for k in range(8):
            vv = Video(youtube_video_id=f"x{i}{k}", channel_id=c.id, title="t", topic="Other", published_at=(NOW - timedelta(days=k + 3)).strftime("%Y-%m-%dT%H:%M:%SZ"))
            s.add(vv)
            s.flush()
            s.add(Observation(video_id=vv.id, channel_id=c.id, observed_at=NOW - timedelta(hours=1), view_count=10_000 + i * 500, like_count=400, comment_count=40, concurrent_viewers=None, is_live=False,
                              classification="REGULAR_VIDEO", source="test"))
    s.commit()
    fake = {"channels": [{"channel_id": 1, "risk": "review", "signals": [{"review": {"status": "confirmed"}}]}, {"channel_id": 2, "risk": "high", "signals": []}]}
    monkeypatch.setattr("api.creator_index.authenticity.scan", lambda *a, **k: fake)
    out = creator_index(s, segment="journalist", now=NOW)
    rows = {r["channel_id"]: r for r in out["channels"]}
    assert rows[1]["index_score"] is None and rows[1]["withheld_reason"] and rows[1]["profile"] == "Not scored"
    assert rows[2]["authenticity_risk"] == "high" and rows[2]["index_score"] is not None


# ------------------------------------------------------------------------------------ package access and users
def test_feature_defaults_can_be_changed_and_admins_always_pass():
    s, _ = make_session()
    assert feature_access.allowed(s, "planner", "sx_analyst", False) and not feature_access.allowed(s, "planner", "sx_intelligence", False)
    assert feature_access.allowed(s, "planner", "sx_free", True)
    feature_access.set_min_plan(s, "planner", "sx_corporate", "admin@x.com")
    assert not feature_access.allowed(s, "planner", "sx_analyst", False) and feature_access.allowed(s, "planner", "sx_enterprise", False)
    row = next(m for m in feature_access.matrix(s) if m["feature"] == "planner")
    assert row["min_plan"] == "sx_corporate" and row["changed"] and row["default"] == "sx_analyst" and row["updated_by"] == "admin@x.com"
    with pytest.raises(ValueError):
        feature_access.set_min_plan(s, "planner", "gold", "a")
    with pytest.raises(ValueError):
        feature_access.set_min_plan(s, "nothing", "sx_pro", "a")


def make_user(s, email, plan="sx_pro", org="Acme Media", admin=False, active=True, status="approved"):
    u = User(email=email, password_hash=hash_password("a long enough pass"), plan=plan, requested_plan=plan, is_admin=admin, active=active, approval_status=status, full_name=email.split("@")[0], organization=org)
    s.add(u)
    s.commit()
    return u


def test_seat_limit_of_a_package_holds_for_create_plan_change_and_switching_on():
    s, _ = make_session()
    for i in range(5):
        make_user(s, f"u{i}@acme.com", plan="sx_corporate")
    with pytest.raises(ValueError, match="5 seats"):
        user_admin.create_user(s, email="u9@acme.com", name="Nine", organization="ACME media", mobile="", plan="sx_corporate")  # same organisation, other spelling
    other = user_admin.create_user(s, email="x@other.com", name="X", organization="Other Org", mobile="", plan="sx_corporate")
    assert other["plan"] == "sx_corporate"
    pro = make_user(s, "pro@acme.com", plan="sx_pro")
    with pytest.raises(ValueError, match="seats"):
        user_admin.set_plan(s, pro.id, "sx_corporate")
    s.get(User, 1).active = False
    s.commit()
    assert user_admin.set_plan(s, pro.id, "sx_corporate")["plan"] == "sx_corporate"
    with pytest.raises(ValueError, match="seats"):
        user_admin.set_active(s, 1, True, acting_user_id=99)
    assert seats_for(s) == 5


def seats_for(s):
    return user_admin.seats_used(s, "Acme Media", "sx_corporate")


def test_created_and_reset_accounts_get_a_one_time_password_that_works_and_unsafe_actions_are_refused():
    s, _ = make_session()
    admin = make_user(s, "boss@x.com", plan="sx_enterprise", org="Boss Co", admin=True)
    out = user_admin.create_user(s, email=" New@Firm.com ", name="New Person", organization="Firm", mobile="+91 99999", plan="sx_pro")
    assert out["email"] == "new@firm.com" and out["approval_status"] == "approved" and len(out["temporary_password"]) >= 12
    user = s.get(User, out["id"])
    assert verify_password(out["temporary_password"], user.password_hash) and "password_hash" not in out
    again = user_admin.reset_password(s, user.id)
    assert not verify_password(out["temporary_password"], s.get(User, user.id).password_hash) and verify_password(again["temporary_password"], s.get(User, user.id).password_hash)
    with pytest.raises(ValueError, match="already exists"):
        user_admin.create_user(s, email="new@firm.com", name="Dup", organization="Firm", mobile="", plan="sx_pro")
    with pytest.raises(ValueError):
        user_admin.create_user(s, email="not-an-email", name="A", organization="B", mobile="", plan="sx_pro")
    with pytest.raises(ValueError):
        user_admin.create_user(s, email="a@b.co", name="A", organization="B", mobile="", plan="gold")
    with pytest.raises(ValueError, match="own account"):
        user_admin.set_active(s, admin.id, False, acting_user_id=admin.id)
    with pytest.raises(ValueError, match="administrator"):
        user_admin.set_plan(s, admin.id, "sx_free")
    assert user_admin.set_active(s, user.id, False, acting_user_id=admin.id)["active"] is False
    listed = user_admin.list_users(s, q="firm")
    assert [u["email"] for u in listed] == ["new@firm.com"] and listed[0]["plan_name"] == "SX Pro"
    assert user_admin.list_users(s, status="pending") == []


def test_admin_http_routes_for_users_and_package_access():
    s, engine = make_session()
    admin = make_user(s, "boss@x.com", plan="sx_enterprise", org="Boss Co", admin=True)
    member = make_user(s, "m@x.com", plan="sx_pro", org="Boss Co")
    app = admin_application(lambda: Session(engine))

    def call(path, who, body):
        raw = json.dumps(body).encode()
        out = {}
        environ = {"REQUEST_METHOD": "POST", "PATH_INFO": path, "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)), "HTTP_AUTHORIZATION": "Bearer " + issue_token(AuthIdentity(who.id, who.email, who.plan, who.is_admin))}
        res = app(environ, lambda status, headers: out.update(status=status))
        return int(out["status"].split()[0]), json.loads(res[0])

    assert call("/api/v1/admin/users/list", member, {})[0] == 403
    status, body = call("/api/v1/admin/users/list", admin, {"q": "m@x"})
    assert status == 200 and [u["email"] for u in body["users"]] == ["m@x.com"] and len(body["plans"]) == 7
    status, body = call("/api/v1/admin/users/plan", admin, {"user_id": member.id, "plan": "sx_analyst"})
    assert status == 200 and body["plan"] == "sx_analyst"
    assert call("/api/v1/admin/users/plan", admin, {"user_id": member.id, "plan": "gold"})[0] == 400
    status, body = call("/api/v1/admin/users/create", admin, {"email": "n@z.com", "name": "N", "organization": "Z", "plan": "sx_idea"})
    assert status == 200 and body["temporary_password"]
    assert call("/api/v1/admin/users/reset-password", admin, {"user_id": member.id})[0] == 200
    assert call("/api/v1/admin/users/active", admin, {"user_id": member.id, "active": False})[0] == 200
    status, body = call("/api/v1/admin/features/list", admin, {})
    assert status == 200 and {f["feature"] for f in body["features"]} >= {"weekly", "planner", "authenticity", "report_builder"}
    status, body = call("/api/v1/admin/features/set", admin, {"feature": "planner", "min_plan": "sx_pro"})
    assert status == 200 and body["min_plan"] == "sx_pro"
    assert call("/api/v1/admin/features/set", admin, {"feature": "planner", "min_plan": "gold"})[0] == 400


def test_channel_group_can_be_chosen_when_adding_and_changed_later():
    from api.admin import set_channel_segment
    s, _ = make_session()
    c = channel(s, "a", "Alpha")
    ident = AuthIdentity(1, "boss@x.com", "sx_enterprise", True)
    assert set_channel_segment(s, ident, c.id, "creator")["segment"] == "creator" and s.get(Channel, c.id).segment == "creator"
    with pytest.raises(ValueError):
        set_channel_segment(s, ident, c.id, "sports")
    with pytest.raises(PermissionError):
        set_channel_segment(s, AuthIdentity(2, "u@x.com", "sx_pro", False), c.id, "news")
