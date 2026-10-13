"""Spikes with the stream behind them, audience movement, hours watched, forecasts with a track record, notes, alerts, data completeness, the public status and methodology, the per-person API limit,
and the collection runs that count as fresh. Invented data in a scratch database."""
import io
import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import alerts, completeness, forecasts, methodology, notes, spikes, status
from api.auth import AuthIdentity, hash_password, issue_token
from api.lab_http import lab_application
from api.live_stats import live_window_stats
from collector.storage import Base, Channel, CollectionRun, Note, Observation, User, Video

IST_SHIFT = timedelta(hours=5, minutes=30)
T0 = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


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


def stream(s, ch, key, start, minutes, level, title=None, started=None, every=1):
    """One live stream read every ``every`` minutes from ``start``; level is a number or a function of the minute."""
    v = s.query(Video).filter_by(youtube_video_id=key).one_or_none() or Video(youtube_video_id=key, channel_id=ch.id, title=title or key, live_started_at=started or start - timedelta(days=60))
    if v.id is None:
        s.add(v)
        s.flush()
    for m in range(0, minutes, every):
        s.add(Observation(video_id=v.id, channel_id=ch.id, observed_at=start + timedelta(minutes=m), view_count=1, concurrent_viewers=level(m) if callable(level) else level, is_live=True, classification="LIVE", source="test"))
    return v


def ist(day, hour):
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC) - IST_SHIFT


def user(s, email, plan="sx_enterprise", admin=False):
    u = User(email=email, password_hash=hash_password("a long enough pass"), plan=plan, requested_plan=plan, is_admin=admin, active=True, approval_status="approved", full_name=email, organization="Org")
    s.add(u)
    s.commit()
    return u


# ------------------------------------------------------------------------------------------------------------------------------ spikes and movement
def test_a_spike_names_the_stream_that_carried_the_rise():
    s, _ = make_session()
    a = channel(s, "a", "Alpha")
    stream(s, a, "main", T0, 120, 5000, title="Alpha LIVE TV")
    stream(s, a, "event", T0 + timedelta(minutes=60), 40, 18000, title="Budget Special LIVE", started=T0 + timedelta(minutes=58))
    s.commit()
    out = spikes.spikes(s, hours=2, now=T0 + timedelta(minutes=120))
    assert len(out["spikes"]) == 1
    sp = out["spikes"][0]
    assert sp["channel"] == "Alpha" and sp["before"] == 5000 and sp["peak"] == 23000 and sp["rise"] == 18000
    assert sp["lead_stream"]["title"] == "Budget Special LIVE" and sp["lead_stream"]["was_new"] is True and sp["lead_stream"]["share_of_rise_percent"] == 100
    assert "Budget Special LIVE" in sp["text"] and "IST" in sp["text"] and "does not say why" in out["note"]


def test_a_steady_channel_has_no_spike():
    s, _ = make_session()
    stream(s, channel(s, "a", "Alpha"), "main", T0, 120, lambda m: 5000 + (m % 7) * 40)
    s.commit()
    assert spikes.spikes(s, hours=2, now=T0 + timedelta(minutes=120))["spikes"] == []


def test_movement_shows_who_gained_while_who_lost_and_the_matched_shift():
    s, _ = make_session()
    a, b = channel(s, "a", "Alpha"), channel(s, "b", "Beta")
    stream(s, a, "am", T0, 61, lambda m: 10000 if m < 30 else 6000)
    stream(s, b, "bm", T0, 61, lambda m: 4000 if m < 30 else 8000)
    s.commit()
    out = spikes.movement(s, minutes=30, now=T0 + timedelta(minutes=60))
    rows = {r["channel"]: r for r in out["channels"]}
    assert rows["Alpha"]["change"] < -3000 and rows["Beta"]["change"] > 3000
    assert out["matched_shift"] > 3000 and out["shifts"][0]["from"] == "Alpha" and out["shifts"][0]["to"] == "Beta" and "individual viewer" in out["note"]


def test_hours_watched_is_the_viewer_hours_of_the_window():
    s, _ = make_session()
    stream(s, channel(s, "a", "Alpha"), "main", T0, 61, 10000)
    s.commit()
    row = live_window_stats(s, start_at=T0, end_at=T0 + timedelta(minutes=60), bucket_seconds=60)["channels"][0]
    assert 9900 <= row["watch_hours"]["all"] <= 10300 and row["watch_hours"]["primary"] == row["watch_hours"]["all"] and row["watch_hours"]["secondary"] == 0


# ------------------------------------------------------------------------------------------------------------------------------ forecasts
def test_forecasts_are_written_before_the_slot_and_scored_after_it():
    s, _ = make_session()
    a, b = channel(s, "a", "Alpha"), channel(s, "b", "Beta")
    for day, level in ((date(2026, 10, 9), 10000), (date(2026, 10, 10), 12000), (date(2026, 10, 11), 14000)):
        stream(s, a, "am", ist(day, 19), 180, level)
        stream(s, b, "bm", ist(day, 19), 180, 4000)
    s.commit()
    target = date(2026, 10, 12)
    assert forecasts.make_predictions(s, target, now=ist(target, 6)) == 2
    assert forecasts.make_predictions(s, target, now=ist(target, 6)) == 0                        # written once, never changed
    assert forecasts.make_predictions(s, target, now=ist(target, 20)) == 0                       # after the slot has begun it is not a forecast
    predicted = {p.channel_id: p for p in s.query(forecasts.Prediction)}
    assert predicted[a.id].predicted == 12000 and predicted[a.id].days_used == 3 and predicted[b.id].predicted == 4000
    stream(s, a, "am", ist(target, 19), 180, 13000)
    stream(s, b, "bm", ist(target, 19), 180, 2000)
    s.commit()
    assert forecasts.score_predictions(s, now=ist(target, 21)) == 0                              # the slot is not over yet
    assert forecasts.score_predictions(s, now=ist(target, 23)) == 2
    scored = {p.channel_id: p for p in s.query(forecasts.Prediction)}
    assert scored[a.id].hit is True and round(scored[a.id].error_percent, 1) == 8.3 and scored[b.id].hit is False and scored[b.id].error_percent == -50.0
    record = forecasts.track_record(s, days=3650)
    assert record["scored"] == 2 and record["hits"] == 1 and record["hit_rate_percent"] == 50.0
    overview = forecasts.forecast_overview(s, now=ist(target, 23))
    assert overview["total_written"] == 2 and "median" in overview["method"] and len(overview["recent"]) == 2


# ------------------------------------------------------------------------------------------------------------------------------ notes
def test_notes_are_written_once_a_day_and_once_a_week(monkeypatch):
    s, _ = make_session()
    fake = {"window": {"from": "2026-10-09", "to": "2026-10-11"}, "kpis": [{"label": "Channels measured", "value": "84"}],
            "findings": [{"headline": "Alpha led", "detail": "d", "confidence": "high", "so_what": "x", "evidence": {"a": 1}}]}
    monkeypatch.setattr(notes, "briefing", lambda *a, **k: fake)
    day = date(2026, 10, 12)
    assert notes.generate_note(s, "daily", day) is True and notes.generate_note(s, "daily", day) is False
    assert notes.generate_note(s, "weekly", day) is True
    listed = notes.list_notes(s)
    assert [n["kind"] for n in listed] == ["daily", "weekly"] and listed[0]["title"] == "Daily note, 12 October 2026" and listed[0]["findings"][0]["headline"] == "Alpha led"
    monkeypatch.setattr(notes, "briefing", lambda *a, **k: {"window": {}, "kpis": [], "findings": []})
    assert notes.generate_note(s, "daily", date(2026, 10, 13)) is False and s.query(Note).count() == 2     # nothing to say: no empty note
    with pytest.raises(ValueError):
        notes.generate_note(s, "monthly", day)
    monday_morning = datetime(2026, 10, 12, 5, 0, tzinfo=UTC)                                          # 10:30 IST, a Monday
    assert notes.due_notes(monday_morning) == [("daily", date(2026, 10, 12)), ("weekly", date(2026, 10, 12))]
    assert notes.due_notes(datetime(2026, 10, 12, 2, 0, tzinfo=UTC)) == []                           # before 09:00 IST
    assert notes.due_notes(datetime(2026, 10, 13, 5, 0, tzinfo=UTC)) == [("daily", date(2026, 10, 13))]


# ------------------------------------------------------------------------------------------------------------------------------ alerts
def test_alerts_fire_once_per_pause_and_belong_to_their_owner():
    s, _ = make_session()
    ch = channel(s, "a", "Alpha")
    me, other = user(s, "me@x.com"), user(s, "other@x.com")
    now = T0 + timedelta(minutes=30)
    stream(s, ch, "main", T0 + timedelta(minutes=20), 1, 5000)           # ten minutes ago
    stream(s, ch, "main", now, 1, 12000)                                 # now
    s.commit()
    above = alerts.create_alert(s, me.id, channel_id=ch.id, kind="live_above", threshold=10000)
    rise = alerts.create_alert(s, me.id, channel_id=ch.id, kind="rise_percent", threshold=50, window_minutes=10)
    assert above["kind_label"] == "Live viewers at or above" and rise["window_minutes"] == 10
    assert alerts.evaluate_alerts(s, now=now) == 2
    assert alerts.evaluate_alerts(s, now=now + timedelta(minutes=1)) == 0                   # inside the pause
    listing = alerts.list_alerts(s, me.id)
    assert listing["unseen"] == 2 and any("rose 140%" in e["message"] for e in listing["events"]) and "not set up" in listing["delivery"]
    alerts.mark_seen(s, me.id)
    assert alerts.list_alerts(s, me.id)["unseen"] == 0 and alerts.list_alerts(s, other.id)["events"] == []
    with pytest.raises(LookupError):
        alerts.delete_alert(s, other.id, above["id"])                                        # not theirs
    alerts.toggle_alert(s, me.id, above["id"], False)
    alerts.delete_alert(s, me.id, rise["id"])
    assert [a["id"] for a in alerts.list_alerts(s, me.id)["alerts"]] == [above["id"]]
    assert alerts.evaluate_alerts(s, now=now + timedelta(hours=3)) == 0                      # switched off


def test_alert_rules_are_checked_when_they_are_made():
    s, _ = make_session()
    ch, off = channel(s, "a", "Alpha"), channel(s, "b", "Beta")
    off.active = False
    me = user(s, "me@x.com")
    s.commit()
    for bad in ({"kind": "nope", "threshold": 5}, {"kind": "live_above", "threshold": -1}, {"kind": "rise_percent", "threshold": 5000}, {"kind": "live_above", "threshold": "many"},
                {"kind": "live_above", "threshold": 10, "window_minutes": 1}, {"kind": "live_above", "threshold": 10, "channel_id": off.id}, {"kind": "live_above", "threshold": 10, "channel_id": 999}):
        with pytest.raises(ValueError):
            alerts.create_alert(s, me.id, **{"channel_id": ch.id, **bad})
    for _ in range(alerts.MAX_PER_PERSON):
        alerts.create_alert(s, me.id, channel_id=ch.id, kind="live_above", threshold=10)
    with pytest.raises(ValueError, match="up to 20"):
        alerts.create_alert(s, me.id, channel_id=ch.id, kind="live_above", threshold=10)


# ------------------------------------------------------------------------------------------------------------------------------ completeness, status, methodology
def test_completeness_counts_the_readings_that_are_there_against_the_ones_that_should_be(monkeypatch):
    monkeypatch.setenv("LIVE_POLL_SECONDS", "60")
    s, _ = make_session()
    ch = channel(s, "a", "Alpha")
    stream(s, ch, "main", T0, 60, lambda m: 9000, every=1)                  # a reading every minute for an hour: complete
    other = channel(s, "b", "Beta")
    v = stream(s, other, "bm", T0, 0, 1)
    for m in list(range(0, 20)) + list(range(40, 60)):                      # a twenty-minute hole in the middle
        s.add(Observation(video_id=v.id, channel_id=other.id, observed_at=T0 + timedelta(minutes=m), view_count=1, concurrent_viewers=500, is_live=True, classification="LIVE", source="test"))
    s.commit()
    out = completeness.channel_day_completeness(s, days=2, now=T0 + timedelta(hours=2))
    rows = {r["channel"]: r for r in out["rows"]}
    assert rows["Alpha"]["completeness_percent"] == 100.0 and rows["Alpha"]["readings"] == 60 and out["poll_seconds"] == 60
    assert rows["Beta"]["completeness_percent"] == pytest.approx(100.0 * 40 / 60, abs=0.2) and rows["Beta"]["expected"] == 60
    assert out["by_day"][0]["lowest_percent"] == rows["Beta"]["completeness_percent"] and "gaps in StatAxis" in out["method"]


def test_status_reports_freshness_and_availability_since_the_first_reading():
    s, _ = make_session()
    ch = channel(s, "a", "Alpha")
    stream(s, ch, "main", T0, 60, 9000, every=1)
    s.add(CollectionRun(started_at=T0, finished_at=T0 + timedelta(minutes=2), status="partial", channels_attempted=84, videos_observed=10))
    s.commit()
    snap = status.status_snapshot(s, now=T0 + timedelta(minutes=62))
    assert snap["status"] == "operational" and snap["channels_measured"] == 1 and snap["readings_stored"] == 60
    assert snap["components"][1]["status"] == "operational"                                     # a partial pass still counts
    day = snap["measurement_availability"][0]
    assert day["percent"] == 100.0 and day["covers_hours"] == pytest.approx(1.0, abs=0.1)         # only the hour since the first reading is claimed
    assert status.status_snapshot(s, now=T0 + timedelta(hours=3))["status"] in ("degraded", "down")
    later = status.availability(s, 24, now=T0 + timedelta(hours=2))
    assert 40 <= later["percent"] <= 60


def test_methodology_is_versioned_and_reads_its_numbers_from_the_calculation():
    m = methodology.methodology()
    assert m["version"] == "STX v0" and abs(sum(m["stx"]["weights"].values()) - 1.0) < 1e-9 and len(m["stx"]["signals"]) == 7
    dates = [c["date"] for c in m["changelog"]]
    assert dates == sorted(dates) and all(c["changes"] for c in m["changelog"])
    assert "30 days" in m["feeds"]["primary"] and "180 seconds" in " ".join(x["definition"] for x in m["measures"]) and "not TV ratings" in " ".join(m["limits"])


def test_collection_that_skipped_a_channel_is_still_fresh_and_interrupted_runs_are_closed():
    from api.operations import collection_health
    from collector.run import close_interrupted_runs
    s, _ = make_session()
    now = datetime.now(UTC)
    s.add(CollectionRun(started_at=now - timedelta(minutes=20), finished_at=now - timedelta(minutes=18), status="partial", channels_attempted=84, videos_observed=1986))
    s.add(CollectionRun(started_at=now - timedelta(hours=3), status="running", channels_attempted=84, videos_observed=0))
    s.add(CollectionRun(started_at=now - timedelta(minutes=5), status="running", channels_attempted=84, videos_observed=0))
    s.commit()
    assert collection_health(s)["fresh"] is True
    assert close_interrupted_runs(s) == 1                                                              # only the one that began long ago
    statuses = sorted(r.status for r in s.query(CollectionRun))
    assert statuses == ["failed", "partial", "running"] and "restart" in s.query(CollectionRun).filter_by(status="failed").one().error_message


# ------------------------------------------------------------------------------------------------------------------------------ HTTP and limits
def test_the_new_routes_follow_the_privileges_and_keep_alerts_private():
    s, engine = make_session()
    ch = channel(s, "a", "Alpha")
    free, intel, pro, corp = user(s, "free@x.com", "sx_free"), user(s, "intel@x.com", "sx_intelligence"), user(s, "pro@x.com", "sx_pro"), user(s, "corp@x.com", "sx_corporate")
    s.commit()
    app = lab_application(lambda: Session(engine))

    def call(who, method, path, body=None, query=""):
        raw = json.dumps(body).encode() if body is not None else b""
        out = {}
        env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)),
               "HTTP_AUTHORIZATION": ("Bearer " + issue_token(AuthIdentity(who.id, who.email, who.plan, who.is_admin))) if who else ""}
        res = app(env, lambda status, headers: out.update(status=status))
        return int(out["status"].split()[0]), json.loads(res[0])

    assert call(None, "GET", "/api/v1/lab/notes")[0] == 401
    assert call(free, "GET", "/api/v1/lab/notes") == (200, {"notes": []})                    # notes are for everyone
    assert call(free, "GET", "/api/v1/lab/spikes")[0] == 403 and call(pro, "GET", "/api/v1/lab/spikes", query="hours=1")[0] == 200
    assert call(intel, "GET", "/api/v1/lab/forecasts")[0] == 403 and call(pro, "GET", "/api/v1/lab/forecasts")[0] == 200            # forecasts start at SX Analyst
    assert call(pro, "GET", "/api/v1/lab/completeness")[0] == 403 and call(corp, "GET", "/api/v1/lab/completeness", query="days=1")[0] == 200
    assert call(free, "POST", "/api/v1/lab/alerts/list", {})[0] == 403
    status, body = call(pro, "POST", "/api/v1/lab/alerts/create", {"channel_id": ch.id, "kind": "live_above", "threshold": 1000})
    assert status == 200 and len(body["alerts"]) == 1
    assert call(pro, "POST", "/api/v1/lab/alerts/create", {"channel_id": ch.id, "kind": "bogus", "threshold": 1000})[0] == 400
    assert call(corp, "POST", "/api/v1/lab/alerts/list", {})[1]["alerts"] == []                                                  # someone else's alerts are not shown
    assert call(corp, "POST", "/api/v1/lab/alerts/delete", {"alert_id": body["alerts"][0]["id"]})[0] == 404
    assert call(pro, "GET", "/api/v1/lab/unknown")[0] == 404
    assert call(pro, "GET", "/api/v1/lab/spikes", query="hours=abc")[0] == 400


def test_one_person_cannot_make_more_calls_a_minute_than_the_limit(monkeypatch):
    from api import gate
    s, engine = make_session()
    u = user(s, "busy@x.com")
    monkeypatch.setattr(gate, "API_PER_MINUTE", 3)
    app = gate.gate_application(lambda: Session(engine), lambda environ, start_response: (start_response("200 OK", []), [b"{}"])[1])

    def call():
        out = {}
        env = {"REQUEST_METHOD": "GET", "PATH_INFO": "/api/v1/channels", "wsgi.input": io.BytesIO(b""), "HTTP_AUTHORIZATION": "Bearer " + issue_token(AuthIdentity(u.id, u.email, u.plan, False))}
        app(env, lambda status, headers: out.update(status=status))
        return int(out["status"].split()[0])

    assert [call() for _ in range(5)] == [200, 200, 200, 429, 429]


def test_the_scheduled_jobs_run_and_a_failing_one_does_not_stop_the_others(monkeypatch):
    from collector import jobs
    s, engine = make_session()
    ch = channel(s, "a", "Alpha")
    me = user(s, "me@x.com")
    now = datetime.now(UTC)
    stream(s, ch, "main", now - timedelta(minutes=1), 1, 20000)
    s.commit()
    alerts.create_alert(s, me.id, channel_id=ch.id, kind="live_above", threshold=1000)
    jobs.minute_jobs(engine, now)
    with Session(engine) as check:
        assert check.query(alerts.AlertEvent).count() == 1
    ran = []
    monkeypatch.setattr("api.notes.generate_note", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr("api.forecasts.score_predictions", lambda *a, **k: ran.append("scored") or 0)
    jobs.periodic_jobs(engine, datetime(2026, 10, 13, 5, 0, tzinfo=UTC))
    assert ran == ["scored"]


def test_the_public_status_and_methodology_need_no_login_and_the_pages_read_them():
    from pathlib import Path

    from api.public_http import public_application
    s, engine = make_session()
    stream(s, channel(s, "a", "Alpha"), "main", datetime.now(UTC) - timedelta(minutes=2), 1, 9000)
    s.commit()
    app = public_application(lambda: Session(engine))

    def get(path):
        out = {}
        res = app({"REQUEST_METHOD": "GET", "PATH_INFO": path, "REMOTE_ADDR": "203.0.113.9", "wsgi.input": io.BytesIO(b"")}, lambda status, headers: out.update(status=status))
        return int(out["status"].split()[0]), json.loads(res[0])

    code, st = get("/api/v1/public/status")
    assert code == 200 and st["status"] in ("operational", "degraded") and "measurement_availability" in st and st["channels_measured"] == 1
    code, m = get("/api/v1/public/methodology")
    assert code == 200 and m["version"] == "STX v0" and m["changelog"]
    assert get("/api/v1/public/nothing")[0] == 404
    dash = Path(__file__).resolve().parent.parent / "dashboard"
    assert "/api/v1/public/status" in (dash / "status.html").read_text(encoding="utf-8") and "/api/v1/public/methodology" in (dash / "methodology.html").read_text(encoding="utf-8")
    site = (dash / "site.js").read_text(encoding="utf-8")
    assert '["/methodology", "Methodology"]' in site and '["/status", "Status"]' in site


def test_every_new_screen_is_in_the_menu_the_screen_list_and_the_privileges():
    from pathlib import Path

    from api import feature_access, me
    ws = (Path(__file__).resolve().parent.parent / "dashboard" / "workspace.html").read_text(encoding="utf-8")
    market = (Path(__file__).resolve().parent.parent / "dashboard" / "market.js").read_text(encoding="utf-8")
    ids = {v[0]: v[2] for v in me.VIEWS}
    for screen, feature in (("spikes", "spikes"), ("forecasts", "forecasts"), ("notes", "notes"), ("alerts", "alerts"), ("completeness", "integrity")):
        assert ids[screen] == feature and feature in feature_access.FEATURES and f'"{screen}"' in ws and f'add("{screen}"' in market
