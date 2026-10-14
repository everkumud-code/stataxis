"""Report e-mails: the subscription choices, the periods, the due-and-sent logic with a stand-in mail service, the one-click unsubscribe, and the mail settings."""
import io
import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import mailer, report_subscriptions as rs
from api.admin_http import admin_application
from api.auth import AuthIdentity, issue_token
from api.lab_http import lab_application
from api.public_http import public_application
from api.report_content import INTERVALS, NotEnoughHistory, build_content, period_for, period_label
from api.report_layouts import sample_content
from collector.storage import Base, Channel, Observation, ReportDelivery, ReportSubscription, User, Video

IST = timedelta(hours=5, minutes=30)


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    monkeypatch.delenv("STAXIS_RESEND_API_KEY", raising=False)


def make():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = Session(engine)
    boss = User(email="boss@x.com", password_hash="x", plan="sx_enterprise", is_admin=True, active=True, approval_status="approved")
    ann = User(email="ann@x.com", password_hash="x", plan="sx_free", active=True, approval_status="approved")
    s.add_all([boss, ann])
    s.commit()
    return s, engine, boss, ann


def real(interval):
    c = sample_content(interval)
    return {**c, "sample": False}


def test_the_periods_end_the_day_before_and_are_sent_on_their_own_days():
    d = date
    assert period_for("daily", d(2026, 10, 14)) == (d(2026, 10, 13), d(2026, 10, 13))
    assert period_for("weekly", d(2026, 10, 12)) == (d(2026, 10, 5), d(2026, 10, 11)) and period_for("weekly", d(2026, 10, 14)) is None       # Mondays: last Monday to Sunday
    assert period_for("fortnightly", d(2026, 10, 15)) == (d(2026, 10, 1), d(2026, 10, 14)) and period_for("fortnightly", d(2026, 11, 1)) == (d(2026, 10, 16), d(2026, 10, 31))
    assert period_for("monthly", d(2026, 10, 1)) == (d(2026, 9, 1), d(2026, 9, 30)) and period_for("monthly", d(2026, 10, 2)) is None
    assert period_for("quarterly", d(2026, 10, 1)) == (d(2026, 7, 1), d(2026, 9, 30)) and period_for("quarterly", d(2027, 1, 1)) == (d(2026, 10, 1), d(2026, 12, 31)) and period_for("quarterly", d(2026, 11, 1)) is None
    assert period_for("half-yearly", d(2026, 10, 1)) == (d(2026, 4, 1), d(2026, 9, 30)) and period_for("half-yearly", d(2027, 4, 1)) == (d(2026, 10, 1), d(2027, 3, 31))
    assert period_for("yearly", d(2026, 4, 1)) == (d(2025, 4, 1), d(2026, 3, 31)) and period_for("yearly", d(2026, 10, 1)) is None
    assert period_label("quarterly", d(2026, 7, 1), d(2026, 9, 30)) == "Jul – Sep 2026 (Q2, FY 2026-27)" and period_label("monthly", d(2026, 9, 1), d(2026, 9, 30)) == "September 2026"
    assert period_label("yearly", d(2025, 4, 1), d(2026, 3, 31)) == "FY 2025-26 (Apr 2025 – Mar 2026)" and period_label("weekly", d(2026, 10, 5), d(2026, 10, 11)) == "5 – 11 Oct 2026"


def test_a_person_chooses_a_report_and_only_their_own_can_be_changed():
    s, _, boss, ann = make()
    out = rs.save_subscription(s, ann, interval="weekly", layout="one_pager", sections=["highlights", "data"], language="Hindi", send_hour=9)
    row = out["subscriptions"][0]
    assert out["email"] == "ann@x.com" and row["interval_label"] == "Weekly report" and row["sections"] == ["highlights", "data"] and row["send_hour"] == 9 and row["language"] == "Hindi" and out["mail_ready"] is False
    with pytest.raises(ValueError):
        rs.save_subscription(s, ann, interval="weekly", layout="one_pager", language="Hindi")                       # the same report twice
    for bad in (dict(interval="hourly", layout="booklet"), dict(interval="daily", layout="poster"), dict(interval="daily", layout="booklet", send_hour=30)):
        with pytest.raises(ValueError):
            rs.save_subscription(s, ann, **bad)
    with pytest.raises(LookupError):
        rs.set_active(s, boss, row["id"], False)                                                                    # somebody else's subscription
    assert rs.set_active(s, ann, row["id"], False)["subscriptions"][0]["active"] is False
    assert rs.delete_subscription(s, ann, row["id"])["subscriptions"] == []
    assert [o["id"] for o in rs.options()["intervals"]] == list(INTERVALS) and rs.options()["note"]


def test_due_reports_are_sent_once_with_the_pdf_and_an_unsubscribe_link(monkeypatch):
    s, _, boss, ann = make()
    mailer.save_settings(s, "boss@x.com", key="re_testkey1234", sender="StatAxis <reports@stataxis.org>")
    rs.save_subscription(s, ann, interval="daily", layout="one_pager", send_hour=8)
    rs.save_subscription(s, ann, interval="monthly", layout="booklet", send_hour=8)
    sent = []
    monkeypatch.setattr(mailer, "_post", lambda key, payload: sent.append((key, payload)) or {"id": f"msg{len(sent)}"})
    monkeypatch.setattr(rs, "build_content", lambda session, interval, a, b, language=None, segment=None: real(interval))
    day = datetime(2026, 10, 14, 3, 0, tzinfo=UTC)                                                                  # 08:30 in India, a Wednesday
    assert rs.send_due(s, now=day) == {"sent": 1, "waiting_history": 0, "waiting_key": 0, "failed": 0}              # the daily report; the monthly one is not due
    key, payload = sent[0]
    assert key == "re_testkey1234" and payload["to"] == ["ann@x.com"] and payload["from"].startswith("StatAxis") and payload["attachments"][0]["filename"].endswith(".pdf")
    assert "STX leader" in payload["subject"] and "Unsubscribe" in payload["html"] and "/unsubscribe?token=" in payload["html"] and payload["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert rs.send_due(s, now=day + timedelta(minutes=10)) == {"sent": 0, "waiting_history": 0, "waiting_key": 0, "failed": 0} and len(sent) == 1       # a period is never sent twice
    first = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)                                                                 # 1 November: the monthly report is due as well as the daily one
    assert rs.send_due(s, now=first)["sent"] == 2 and s.query(ReportDelivery).filter_by(status="sent").count() == 3
    early = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)                                                                 # 05:30: before the chosen hour
    assert rs.send_due(s, now=early)["sent"] == 0


def test_without_a_mail_key_or_enough_history_nothing_is_lost_or_half_sent(monkeypatch):
    s, _, _, ann = make()
    rs.save_subscription(s, ann, interval="daily", layout="one_pager", send_hour=8)
    day = datetime(2026, 10, 14, 3, 0, tzinfo=UTC)
    assert rs.send_due(s, now=day)["waiting_key"] == 1 and s.query(ReportDelivery).count() == 0                     # no key: nothing recorded, tried again later
    mailer.save_settings(s, "boss@x.com", key="re_testkey1234")
    def not_yet(*_a, **_k):
        raise NotEnoughHistory("StatAxis has measured 1 of the 30 days of this period")
    monkeypatch.setattr(rs, "build_content", not_yet)
    assert rs.send_due(s, now=day)["waiting_history"] == 1 and s.query(ReportDelivery).one().status == "waiting_history"
    sent = []
    monkeypatch.setattr(mailer, "_post", lambda key, payload: sent.append(payload) or {"id": "m1"})
    monkeypatch.setattr(rs, "build_content", lambda session, interval, a, b, language=None, segment=None: real(interval))
    assert rs.send_due(s, now=day + timedelta(minutes=10))["sent"] == 1 and s.query(ReportDelivery).one().status == "sent" and len(sent) == 1   # once enough is measured, the waiting report goes out
    def refuse(key, payload):
        raise mailer.MailError("the mail service answered 403")
    monkeypatch.setattr(mailer, "_post", refuse)
    rs.save_subscription(s, ann, interval="daily", layout="booklet", send_hour=8)
    assert rs.send_due(s, now=day + timedelta(minutes=20))["failed"] == 1 and s.query(ReportDelivery).filter_by(status="failed").one().detail.startswith("the mail service answered 403")


def test_send_now_goes_to_your_own_address_a_few_times_an_hour(monkeypatch):
    s, _, _, ann = make()
    sub_id = rs.save_subscription(s, ann, interval="weekly", layout="one_pager")["subscriptions"][0]["id"]
    monkeypatch.setattr(rs, "build_content", lambda session, interval, a, b, language=None, segment=None: real(interval))
    with pytest.raises(ValueError):
        rs.send_now(s, ann, sub_id)                                                                                 # no key yet: a clear message, not a crash
    mailer.save_settings(s, "boss@x.com", key="re_testkey1234")
    sent = []
    monkeypatch.setattr(mailer, "_post", lambda key, payload: sent.append(payload) or {"id": "m"})
    now = datetime.now(UTC)                                                                                          # the deliveries are stamped with the real clock
    for _ in range(rs.MANUAL_PER_HOUR):
        assert rs.send_now(s, ann, sub_id, now=now)["sent_to"] == "ann@x.com"
    with pytest.raises(ValueError):
        rs.send_now(s, ann, sub_id, now=now)
    assert len(sent) == rs.MANUAL_PER_HOUR and all(p["to"] == ["ann@x.com"] for p in sent)


def test_the_real_report_is_built_from_the_measured_videos_and_waits_for_history():
    s = Session(create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False}))
    Base.metadata.create_all(s.get_bind())
    day = date(2026, 10, 10)
    start = datetime(2026, 10, 10, 6, 0, tzinfo=UTC)
    for i, (name, views) in enumerate((("Alpha", 4_000_000), ("Beta", 2_500_000), ("Gamma", 900_000))):
        c = Channel(youtube_channel_id=f"c{i}", name=name, network="n", language="Hindi", region="India", segment="news")
        s.add(c)
        s.flush()
        v = Video(youtube_video_id=f"v{i}", channel_id=c.id, title="t", topic="Politics", published_at=start.strftime("%Y-%m-%dT%H:%M:%SZ"))
        s.add(v)
        s.flush()
        s.add(Observation(video_id=v.id, channel_id=c.id, observed_at=start + timedelta(hours=3), view_count=views, like_count=1, comment_count=1, is_live=False, classification="REGULAR_VIDEO", source="t"))
    s.commit()
    c = build_content(s, "daily", day, day)
    assert [r["name"] for r in c["ranking"]] == ["Alpha", "Beta", "Gamma"] and c["ranking"][0]["views"] == pytest.approx(4.0) and c["kpis"][0]["value"] == "7.4M" and c["period"] == "10 Oct 2026"
    assert c["title"].endswith("Daily report") and len(c["trend"]["points"]) == 12 and c["highlights"] and c["findings"] and c["viewpoint"]
    with pytest.raises(NotEnoughHistory):
        build_content(s, "monthly", date(2026, 9, 1), date(2026, 9, 30))                                           # September was never measured
    with pytest.raises(NotEnoughHistory):
        build_content(s, "yearly", date(2025, 4, 1), date(2026, 3, 31))
    with pytest.raises(NotEnoughHistory):
        build_content(s, "weekly", date(2026, 10, 5), date(2026, 10, 11))                                            # two days measured of seven: below 60%


def call(app, method, path, token=None, body=None, query=""):
    raw = json.dumps(body).encode() if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw), "REMOTE_ADDR": "1.2.3.4"}
    if token:
        env["HTTP_AUTHORIZATION"] = "Bearer " + token
    out = {}
    result = app(env, lambda status, headers, *a: out.update(status=int(status.split()[0])))
    return out["status"], json.loads(b"".join(result) or b"{}")


def test_the_screens_talk_to_the_server_and_the_unsubscribe_link_works_without_a_login():
    s, engine, boss, ann = make()
    factory = lambda: Session(engine)  # noqa: E731
    lab, admin, public = lab_application(factory), admin_application(factory), public_application(factory)
    token = issue_token(AuthIdentity(ann.id, ann.email, ann.plan, False))
    btoken = issue_token(AuthIdentity(boss.id, boss.email, boss.plan, True))
    assert call(lab, "GET", "/api/v1/lab/report-subscriptions")[0] == 401
    status, body = call(lab, "POST", "/api/v1/lab/report-subscriptions/save", token, {"interval": "weekly", "layout": "booklet", "sections": ["findings"], "send_hour": 7})
    assert status == 200 and body["subscriptions"][0]["layout_label"] == "Booklet" and body["subscriptions"][0]["sections"] == ["findings"]
    assert call(lab, "POST", "/api/v1/lab/report-subscriptions/save", token, {"interval": "weekly", "layout": "poster"})[0] == 400
    assert call(lab, "POST", "/api/v1/lab/report-subscriptions/toggle", btoken, {"id": body["subscriptions"][0]["id"], "active": False})[0] == 404         # not the admin's subscription
    # the mail settings: admin only, the key is never returned in full
    assert call(admin, "GET", "/api/v1/admin/email", token)[0] == 403
    status, mail = call(admin, "POST", "/api/v1/admin/email/save", btoken, {"key": "re_abcdefghijkl", "from": "StatAxis <reports@stataxis.org>"})
    assert status == 200 and mail["configured"] is True and mail["key_hint"] == "…ijkl" and "re_abcdefghijkl" not in json.dumps(mail)
    assert call(admin, "POST", "/api/v1/admin/email/save", btoken, {"key": "nope"})[0] == 400 and call(admin, "POST", "/api/v1/admin/email/save", btoken, {"from": "no-address"})[0] == 400
    # one click, no login
    sub = s.query(ReportSubscription).one()
    assert sub.active is True
    assert call(public, "POST", "/api/v1/public/reports/unsubscribe", None, {"token": sub.unsubscribe_token})[0] == 200
    s.expire_all()
    assert s.query(ReportSubscription).one().active is False
    assert call(public, "POST", "/api/v1/public/reports/unsubscribe", None, {"token": "not-a-token"})[0] == 200          # the answer never says whether a token existed
    sub.active = True
    s.commit()
    assert call(public, "POST", "/api/v1/public/reports/unsubscribe", None, query=f"token={sub.unsubscribe_token}")[0] == 200
    s.expire_all()
    assert s.query(ReportSubscription).one().active is False


def test_the_report_screens_and_the_page_that_unsubscribes_are_in_the_workspace():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "dashboard"
    market = (root / "market.js").read_text(encoding="utf-8")
    assert 'add("reportmail"' in market and 'add("adm-email"' in market and "/api/v1/lab/report-subscriptions/save" in market and "/api/v1/admin/email/test" in market
    page = (root / "unsubscribe.html").read_text(encoding="utf-8")
    assert "/api/v1/public/reports/unsubscribe" in page and "noindex" in page and "x.com/stataxis" in page
