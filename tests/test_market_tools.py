"""Weekly views, prime time, creator score, media planner, authenticity radar and their HTTP layer, on invented data in a scratch database."""
import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api import authenticity
from api.auth import AuthIdentity, issue_token
from api.market_http import market_application
from api.market_tools import creator_scores, media_plan, prime_time, quota_need, weekly_views
from collector.storage import AuthenticityReview, Base, Channel, ChannelStats, Observation, Video

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)  # 11:30 in India on 12 Oct


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    authenticity.scan.cache_clear()


def make_session():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def channel(session, key, name, segment="news", language="Hindi"):
    c = Channel(youtube_channel_id=key, name=name, network="n", language=language, region="India", segment=segment)
    session.add(c)
    session.flush()
    return c


def video(session, ch, key, published, views, likes=0, comments=0, observed=NOW - timedelta(hours=1), live_started=None):
    v = Video(youtube_video_id=key, channel_id=ch.id, title=key, published_at=published.strftime("%Y-%m-%dT%H:%M:%SZ"), live_started_at=live_started)
    session.add(v)
    session.flush()
    session.add(Observation(video_id=v.id, channel_id=ch.id, observed_at=observed, view_count=views, like_count=likes, comment_count=comments, concurrent_viewers=None, is_live=False, classification="VOD", source="test"))
    return v


def live_day(session, ch, vid_key, day_ist, start_hour, end_hour, level, wobble=0):
    """One-minute live samples between two Indian hours of a day."""
    start = datetime(day_ist.year, day_ist.month, day_ist.day, tzinfo=UTC) + timedelta(hours=start_hour) - timedelta(hours=5, minutes=30)
    v = session.query(Video).filter_by(youtube_video_id=vid_key).one_or_none()
    if v is None:
        v = Video(youtube_video_id=vid_key, channel_id=ch.id, title=vid_key, live_started_at=start - timedelta(days=60))
        session.add(v)
        session.flush()
    for m in range((end_hour - start_hour) * 60):
        session.add(Observation(video_id=v.id, channel_id=ch.id, observed_at=start + timedelta(minutes=m), view_count=1, concurrent_viewers=level + (wobble if m % 2 else -wobble), is_live=True, classification="LIVE", source="test"))


# ------------------------------------------------------------------------------------ weekly views
def test_weekly_views_adds_up_uploads_per_channel_with_share_and_stale_flags():
    s = make_session()
    a, b = channel(s, "a", "Alpha"), channel(s, "b", "Beta")
    day = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
    video(s, a, "a1", day, 600_000, 30_000, 2_000)
    video(s, a, "a2", day + timedelta(days=1), 200_000, 8_000, 500, observed=NOW - timedelta(hours=30))  # stale
    video(s, b, "b1", day, 200_000, 4_000, 100)
    video(s, b, "b_old", day - timedelta(days=20), 9_000_000)  # uploaded long before: not counted
    s.commit()
    out = weekly_views(s, start_date="2026-10-05", end_date="2026-10-11", now=NOW)
    g = out["groups"][0]
    assert g["label"] == "Hindi News" and g["total_views"] == 1_000_000
    first, second = g["channels"]
    assert (first["name"], first["views"], first["share_percent"], first["videos"], first["stale_videos"]) == ("Alpha", 800_000, 80.0, 2, 1)
    assert (second["name"], second["views"], second["share_percent"]) == ("Beta", 200_000, 20.0)
    assert first["rank"] == 1 and "method" in out and out["timezone"] == "IST"


def test_weekly_views_groups_follow_the_segment_and_validate_dates():
    s = make_session()
    biz = channel(s, "z", "Money", segment="business", language="English")
    video(s, biz, "z1", datetime(2026, 10, 7, tzinfo=UTC), 1_000)
    s.commit()
    assert [g["label"] for g in weekly_views(s, start_date="2026-10-05", end_date="2026-10-11", now=NOW)["groups"]] == ["Business News"]
    assert weekly_views(s, start_date="2026-10-05", end_date="2026-10-11", segment="print", now=NOW)["groups"] == []
    with pytest.raises(ValueError):
        weekly_views(s, start_date="2026-10-11", end_date="2026-10-05")
    with pytest.raises(ValueError):
        weekly_views(s, start_date="nonsense", end_date="2026-10-05")
    with pytest.raises(ValueError):
        weekly_views(s, start_date="2026-01-01", end_date="2026-10-05")


# ------------------------------------------------------------------------------------ prime time and planner
def seeded_live(s):
    a, b = channel(s, "a", "Alpha"), channel(s, "b", "Beta")
    for i in range(1, 8):  # 5 to 11 Oct
        d = datetime(2026, 10, 4 + i).date()
        live_day(s, a, "alive", d, 20, 22, 10_000, wobble=200)
        live_day(s, b, "blive", d, 20, 22, 4_000, wobble=100)
    s.commit()
    return a, b


def test_prime_time_averages_each_slot_over_the_days_and_skips_empty_slots():
    s = make_session()
    seeded_live(s)
    out = prime_time(s, start_date="2026-10-05", end_date="2026-10-11", now=NOW)
    slots = {x["slot"]: x for x in out["slots"]}
    assert slots["17:00-18:00"]["top"] == []  # nobody live then: nothing is invented
    top = slots["20:00-21:00"]["top"]
    assert [r["name"] for r in top] == ["Alpha", "Beta"]
    assert 9_900 <= top[0]["average_concurrent"] <= 10_100 and top[0]["days_seen"] == 7
    assert top[0]["peak_concurrent"] >= 10_000


def test_media_plan_ranks_by_audience_and_cost_and_splits_a_budget_with_a_cap():
    s = make_session()
    a, b = seeded_live(s)
    out = media_plan(s, start_hour=20, end_hour=22, days=7, rates={a.id: 50_000, b.id: 10_000}, budget=100_000, max_share=0.6, now=NOW)
    rows = {r["name"]: r for r in out["channels"]}
    assert rows["Alpha"]["rank"] == 1 and rows["Beta"]["rank"] == 2
    assert rows["Alpha"]["days_seen"] == 7 and rows["Alpha"]["stability"] >= 95
    assert rows["Alpha"]["cost_per_1000"] == pytest.approx(5000, rel=0.02) and rows["Beta"]["cost_per_1000"] == pytest.approx(2500, rel=0.02)
    assert rows["Beta"]["value_index"] > rows["Alpha"]["value_index"]
    plan = out["plan"]
    assert plan["spent"] <= 100_000 and plan["left"] >= 0
    lines = {line["name"]: line for line in plan["lines"]}
    assert lines["Alpha"]["spend"] <= 60_000 and lines["Beta"]["spots"] >= 1  # cap of 60% holds, the cheaper audience gets the rest
    assert "unique reach" in out["method"]


def test_media_plan_never_buys_a_high_risk_channel_and_checks_inputs():
    s = make_session()
    a, b = seeded_live(s)
    risk = {a.id: {"risk": "high", "signals": ["live_spike"]}}
    plan = media_plan(s, start_hour=20, end_hour=22, days=7, rates={a.id: 10_000, b.id: 10_000}, budget=50_000, authenticity=risk, now=NOW)["plan"]
    assert [line["name"] for line in plan["lines"]] == ["Beta"] and plan["skipped_high_risk"] == ["Alpha"]
    for bad in (dict(start_hour=22, end_hour=20), dict(start_hour=0, end_hour=20), dict(start_hour=20, end_hour=22, days=1), dict(start_hour=20, end_hour=22, budget=-1)):
        with pytest.raises(ValueError):
            media_plan(s, now=NOW, **bad)


# ------------------------------------------------------------------------------------ creator score
def test_creator_score_ranks_reach_pull_engagement_and_says_how_sure_it_is():
    s = make_session()
    chans = []
    for i, (subs, views, likes) in enumerate([(1_000_000, 900_000, 45_000), (500_000, 300_000, 9_000), (200_000, 150_000, 1_500), (100_000, 20_000, 200), (50_000, 30_000, 2_100)]):
        c = channel(s, f"c{i}", f"Creator{i}", segment="commentator")
        chans.append(c)
        s.add(ChannelStats(channel_id=c.id, observed_at=NOW - timedelta(days=6), subscribers=subs, total_views=1))
        s.add(ChannelStats(channel_id=c.id, observed_at=NOW - timedelta(hours=2), subscribers=int(subs * 1.01), total_views=1))
        for k in range(10):
            video(s, c, f"c{i}v{k}", NOW - timedelta(days=k + 1), views, likes, likes // 10)
    s.commit()
    out = creator_scores(s, segment="commentator", days=30, now=NOW)
    names = [r["name"] for r in out["channels"]]
    assert names[0] == "Creator0" and names[-1] == "Creator3"
    top = out["channels"][0]
    assert 0 <= top["score"] <= 100 and set(top["parts"]) >= {"reach", "pull", "engagement", "consistency"}
    assert top["videos_measured"] == 10 and top["growth_percent"] == pytest.approx(1.0, abs=0.01)
    assert top["confidence_label"] in {"medium", "high"} and "method" in out


def test_creator_score_is_honest_when_there_are_too_few_channels():
    s = make_session()
    c = channel(s, "x", "Solo", segment="commentator")
    video(s, c, "v1", NOW - timedelta(days=2), 1_000)
    s.commit()
    out = creator_scores(s, segment="commentator", now=NOW)
    assert out["channels"][0]["score"] is None and out["note"]
    with pytest.raises(ValueError):
        creator_scores(s, days=3)


# ------------------------------------------------------------------------------------ authenticity radar
def codes(result, name):
    row = next(r for r in result["channels"] if r["name"] == name)
    return row, {sig["code"] for sig in row["signals"]}


def steady_series(s, ch, key, start, n=14, step=1000, minutes=30, likes_per_view=0.04, base_views=100_000):
    v = Video(youtube_video_id=key, channel_id=ch.id, title=key, published_at=(start - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    s.add(v)
    s.flush()
    views = base_views
    for i in range(n):
        s.add(Observation(video_id=v.id, channel_id=ch.id, observed_at=start + timedelta(minutes=minutes * i), view_count=views, like_count=int(views * likes_per_view), concurrent_viewers=None, is_live=False, classification="VOD", source="test"))
        views += step
    return v


def test_radar_flags_low_engagement_against_comparable_channels_and_leaves_normal_ones_alone():
    s = make_session()
    rates = [0.040, 0.041, 0.039, 0.042, 0.038, 0.0015]
    for i, rate in enumerate(rates):
        c = channel(s, f"e{i}", f"Chan{i}")
        for k in range(6):
            video(s, c, f"e{i}v{k}", NOW - timedelta(days=k + 1), 100_000, int(100_000 * rate), 300)
    s.commit()
    res = authenticity.scan(s, days=7, now=NOW, use_cache=False)
    row, found = codes(res, "Chan5")
    assert "low_engagement" in found and row["risk"] == "review"
    assert all(r["risk"] == "low" for r in res["channels"] if r["name"] != "Chan5")
    assert "never" not in res["method"] and "not proof" in res["method"]


def test_radar_flags_a_view_surge_without_likes_and_identical_steps():
    s = make_session()
    surge = channel(s, "s", "Surge")
    steps = channel(s, "t", "Steps")
    start = NOW - timedelta(hours=10)
    v = steady_series(s, surge, "sv", start, n=14)
    obs = s.query(Observation).filter_by(video_id=v.id).order_by(Observation.observed_at).all()
    jump = 80_000
    for o in obs[7:]:
        o.view_count += jump  # the surge arrives between sample 6 and 7 and brings no new likes
        o.like_count = obs[6].like_count + (o.id - obs[6].id) * 10
    steady_series(s, steps, "tv", start, n=12, step=500)
    s.commit()
    res = authenticity.scan(s, days=7, now=NOW, use_cache=False)
    row, found = codes(res, "Surge")
    assert "view_burst" in found
    evidence = next(sig for sig in row["signals"] if sig["code"] == "view_burst")["evidence"]
    assert evidence["views_added"] >= 80_000 and evidence["new_likes"] < 100
    _, found = codes(res, "Steps")
    assert "mechanical_steps" in found


def test_radar_flags_live_spike_and_flat_line_but_not_a_natural_stream():
    s = make_session()
    spike, flat, normal = channel(s, "p", "Spike"), channel(s, "f", "Flat"), channel(s, "n", "Natural")
    start = NOW - timedelta(hours=5)

    def stream(ch, key, values):
        v = Video(youtube_video_id=key, channel_id=ch.id, title=key, live_started_at=start - timedelta(days=30))
        s.add(v)
        s.flush()
        for i, val in enumerate(values):
            s.add(Observation(video_id=v.id, channel_id=ch.id, observed_at=start + timedelta(seconds=30 * i), view_count=1, concurrent_viewers=val, is_live=True, classification="LIVE", source="test"))

    stream(spike, "sp", [5000] * 12 + [20_000, 21_000] + [5200] * 10)
    stream(flat, "fl", [3000] * 70)
    stream(normal, "nl", [5000 + (i % 7) * 90 - (i % 5) * 40 for i in range(70)])
    s.commit()
    res = authenticity.scan(s, days=7, now=NOW, use_cache=False)
    assert "live_spike" in codes(res, "Spike")[1]
    assert "live_flatline" in codes(res, "Flat")[1]
    assert codes(res, "Natural")[0]["risk"] == "low"


def test_an_admin_decision_is_kept_and_a_cleared_flag_stops_counting():
    s = make_session()
    flat = channel(s, "f", "Flat")
    start = NOW - timedelta(hours=2)
    v = Video(youtube_video_id="fl", channel_id=flat.id, title="fl", live_started_at=start - timedelta(days=30))
    s.add(v)
    s.flush()
    for i in range(70):
        s.add(Observation(video_id=v.id, channel_id=flat.id, observed_at=start + timedelta(seconds=30 * i), view_count=1, concurrent_viewers=3000, is_live=True, classification="LIVE", source="test"))
    s.commit()
    assert authenticity.scan(s, now=NOW, use_cache=False)["channels"][0]["risk"] == "review"
    authenticity.set_review(s, channel_id=flat.id, signal="live_flatline", status="cleared", note="Studio feed, checked with the channel", by="admin@x.com")
    row = authenticity.scan(s, now=NOW, use_cache=False)["channels"][0]
    assert row["risk"] == "low" and row["signals"][0]["review"]["status"] == "cleared" and row["signals"][0]["review"]["by"] == "admin@x.com"
    assert s.query(AuthenticityReview).count() == 1
    with pytest.raises(ValueError):
        authenticity.set_review(s, channel_id=flat.id, signal="nope", status="cleared", note="", by="a")
    with pytest.raises(ValueError):
        authenticity.set_review(s, channel_id=flat.id, signal="live_flatline", status="maybe", note="", by="a")


# ------------------------------------------------------------------------------------ quota and http
def test_quota_need_says_what_to_ask_for():
    small = quota_need(6, 600, 30)
    big = quota_need(60, 600, 30)
    assert small["fits"] and not big["fits"]
    assert big["quota_to_request"] > 10_000 and big["quota_to_request"] % 1000 == 0


def call(app, method, path, token=None, body=None, query=""):
    raw = json.dumps(body).encode() if body is not None else b""
    out = {}
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw))}
    if token:
        environ["HTTP_AUTHORIZATION"] = "Bearer " + token
    result = app(environ, lambda status, headers: out.update(status=status))
    return int(out["status"].split()[0]), json.loads(result[0])


def test_http_gates_each_tool_by_package_reads_the_package_live_and_only_admins_record_decisions():
    from sqlalchemy.pool import StaticPool
    from api import feature_access
    from collector.storage import User
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        c = channel(s, "a", "Alpha")
        video(s, c, "a1", datetime.now(UTC) - timedelta(days=1), 1_000)
        for uid, email, plan, admin in ((1, "f@x.com", "sx_free", False), (2, "idea@x.com", "sx_idea", False), (3, "pro@x.com", "sx_pro", False), (4, "a@x.com", "sx_enterprise", True)):
            s.add(User(id=uid, email=email, password_hash="x", plan=plan, is_admin=admin, active=True, approval_status="approved"))
        s.commit()
        cid = c.id
    app = market_application(lambda: Session(engine))
    tok = lambda uid, email, plan, admin=False: issue_token(AuthIdentity(uid, email, plan, admin))
    free, idea, pro, admin = tok(1, "f@x.com", "sx_free"), tok(2, "idea@x.com", "sx_idea"), tok(3, "pro@x.com", "sx_pro"), tok(4, "a@x.com", "sx_enterprise", True)
    assert call(app, "GET", "/api/v1/market/weekly")[0] == 401
    status, body = call(app, "GET", "/api/v1/market/weekly", free)
    assert status == 403 and "SX Idea" in body["error"] and "SX Free" in body["error"]
    assert call(app, "GET", "/api/v1/market/weekly", idea)[0] == 200
    assert call(app, "GET", "/api/v1/market/weekly", idea, query="from=bad&to=2026-10-01")[0] == 400
    assert call(app, "GET", "/api/v1/market/creators", idea)[0] == 403          # needs SX Intelligence
    assert call(app, "POST", "/api/v1/market/planner", idea, {"start_hour": 20, "end_hour": 22})[0] == 403  # needs SX Analyst
    assert call(app, "GET", "/api/v1/market/authenticity", idea)[0] == 403      # needs SX Pro
    assert call(app, "GET", "/api/v1/market/authenticity", pro)[0] == 200
    status, body = call(app, "POST", "/api/v1/market/planner", pro, {"start_hour": 20, "end_hour": 22, "days": 7})
    assert status == 200 and body["channels"] == []
    assert call(app, "GET", "/api/v1/market/quota", pro)[0] == 403              # admin only
    status, body = call(app, "GET", "/api/v1/market/quota", admin)
    assert status == 200 and body["active_channels"] == 1
    review = {"channel_id": cid, "signal": "live_spike", "status": "watching", "note": "keep an eye"}
    assert call(app, "POST", "/api/v1/market/authenticity/review", pro, review)[0] == 403
    assert call(app, "POST", "/api/v1/market/authenticity/review", admin, review)[0] == 200
    assert call(app, "GET", "/api/v1/market/nothing", pro)[0] == 404
    # the admin lowers a tool to SX Free: it opens at once, with the same login
    with Session(engine) as s:
        feature_access.set_min_plan(s, "weekly", "sx_free", "a@x.com")
    assert call(app, "GET", "/api/v1/market/weekly", free)[0] == 200
    # switching an account off closes every tool at once, even with a login that has not run out
    with Session(engine) as s:
        s.get(User, 3).active = False
        s.commit()
    assert call(app, "GET", "/api/v1/market/authenticity", pro)[0] == 401


def test_the_planner_counts_today_once_the_chosen_hours_have_ended():
    s = make_session()
    seeded_live(s)
    morning = media_plan(s, start_hour=20, end_hour=22, days=7, now=NOW)                      # 11:30 IST: tonight is not over, the last complete day is yesterday
    assert morning["window"]["days"][-1] == "2026-10-11"
    night = media_plan(s, start_hour=20, end_hour=22, days=7, now=datetime(2026, 10, 12, 17, 0, tzinfo=UTC))   # 22:30 IST: today's 20:00 to 22:00 is over
    assert night["window"]["days"][-1] == "2026-10-12" and night["window"]["days"][0] == "2026-10-06"
    assert {r["name"]: r["days_seen"] for r in night["channels"]} == {"Alpha": 6, "Beta": 6}   # 6 to 11 Oct had samples; 12 Oct had none yet


def test_an_empty_planner_says_why_instead_of_a_bare_empty_table():
    s = make_session()
    nothing = media_plan(s, start_hour=20, end_hour=22, days=7, now=NOW)
    assert nothing["channels"] == [] and nothing["data_since"] is None and "No live viewer samples" in nothing["note"]
    a = channel(s, "a", "Alpha")
    live_day(s, a, "early", datetime(2026, 10, 12).date(), 0, 5, 3_000)   # samples exist, but only from the small hours of 12 Oct
    s.commit()
    out = media_plan(s, start_hour=20, end_hour=22, days=7, now=NOW)
    assert out["channels"] == [] and out["data_since"].startswith("2026-10-12T00:00") and "only since 12 Oct 00:00 IST" in out["note"] and "20:00 to 22:00" in out["note"]
    full = media_plan(s, start_hour=0, end_hour=5, days=7, now=NOW)       # a window that has ended today is counted
    assert [r["name"] for r in full["channels"]] == ["Alpha"] and full["note"] is None


def test_radar_notices_a_stream_whose_audience_never_dips_when_comparable_channels_do():
    s = make_session()
    start = NOW - timedelta(hours=5)
    real = [channel(s, f"r{i}", f"Real {i}") for i in range(4)]
    odd = channel(s, "o", "Level")

    def stream(ch, key, values):
        v = Video(youtube_video_id=key, channel_id=ch.id, title=key, live_started_at=start - timedelta(days=30))
        s.add(v)
        s.flush()
        for i, val in enumerate(values):
            s.add(Observation(video_id=v.id, channel_id=ch.id, observed_at=start + timedelta(seconds=60 * i), view_count=1, concurrent_viewers=val, is_live=True, classification="LIVE", source="test"))

    n = 240   # four hours, one reading a minute
    for k, ch in enumerate(real):   # a commercial break every twelve minutes: the audience falls 15% for three minutes
        stream(ch, f"rs{k}", [int((9000 + 400 * k) * (0.85 if (i % 12) in (8, 9, 10) else 1.0)) + (i % 5) * 20 for i in range(n)])
    stream(odd, "od", [9000 + (i % 7) * 25 - (i % 4) * 15 for i in range(n)])   # stays level all day
    s.commit()
    res = authenticity.scan(s, days=7, now=NOW, use_cache=False)
    row, found = codes(res, "Level")
    assert "no_ad_dips" in found
    evidence = next(sig for sig in row["signals"] if sig["code"] == "no_ad_dips")["evidence"]
    assert evidence["dips_per_hour"] <= 0.15 * evidence["peer_median_per_hour"] and evidence["peers"] == 4 and evidence["hours"] >= 3
    for i in range(4):
        assert "no_ad_dips" not in codes(res, f"Real {i}")[1]


def test_dip_stats_counts_breaks_and_stays_quiet_on_short_or_small_streams():
    from datetime import timedelta as td
    from types import SimpleNamespace as NS
    start = NOW - td(hours=6)
    rows = lambda vals: [NS(observed_at=start + td(seconds=60 * i), concurrent_viewers=v) for i, v in enumerate(vals)]
    broken = authenticity.dip_stats(rows([int(8000 * (0.85 if (i % 15) in (10, 11) else 1.0)) for i in range(240)]))
    assert broken and 12 <= broken["dips"] <= 17 and 0.9 <= broken["per_hour"] <= 4.5          # about one break every quarter hour
    assert authenticity.dip_stats(rows([8000] * 240))["dips"] == 0
    assert authenticity.dip_stats(rows([8000] * 100)) is None and authenticity.dip_stats(rows([300] * 240)) is None   # too short, too small


def test_every_radar_flag_says_how_long_it_lasted_and_when_in_indian_time():
    s = make_session()
    spike, flat = channel(s, "p", "Spike"), channel(s, "f", "Flat")
    start = NOW - timedelta(hours=5)

    def stream(ch, key, values):
        v = Video(youtube_video_id=key, channel_id=ch.id, title=key, live_started_at=start - timedelta(days=30))
        s.add(v)
        s.flush()
        for i, val in enumerate(values):
            s.add(Observation(video_id=v.id, channel_id=ch.id, observed_at=start + timedelta(seconds=30 * i), view_count=1, concurrent_viewers=val, is_live=True, classification="LIVE", source="test"))

    stream(spike, "sp", [5000] * 12 + [20_000, 21_000] + [5200] * 10)
    stream(flat, "fl", [3000] * 70)
    s.commit()
    res = authenticity.scan(s, days=7, now=NOW, use_cache=False)
    burst = next(x for x in codes(res, "Spike")[0]["signals"] if x["code"] == "live_spike")
    assert burst["lasted"] == "60 seconds" and burst["lasted_seconds"] == 60 and burst["from_ist"] and burst["to_ist"] and burst["episodes"][0]["lasted"] == "60 seconds"
    line = next(x for x in codes(res, "Flat")[0]["signals"] if x["code"] == "live_flatline")
    assert line["lasted_seconds"] == 69 * 30 and line["lasted"] == "34 minutes" and line["from_ist"].endswith(("AM", "PM")) and line["to_ist"].endswith(("AM", "PM"))
    assert authenticity.lasted_text(40) == "40 seconds" and authenticity.lasted_text(720) == "12 minutes" and authenticity.lasted_text(6.5 * 3600) == "6.5 hours" and authenticity.lasted_text(3 * 86400) == "3 days"
    ist = authenticity._ist_label(datetime(2026, 10, 12, 13, 30, tzinfo=UTC))
    assert ist == "12 Oct, 7:00 PM"                                                                                          # 13:30 UTC is 7 pm in India
