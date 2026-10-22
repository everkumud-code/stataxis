"""Forgotten passwords: the e-mail code, the backup codes, the pages and routes, the limits that stop guessing, and the guarantee that the answer never says whether an account exists.
Invented data in a scratch database; no mail is sent (the mail call is replaced)."""
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import admin_reset, mailer, recovery
from api.auth import AuthIdentity, hash_password, issue_token, verify_password
from api.auth_http import auth_application
from api.rate_limit import limiter
from collector.storage import Base, RecoveryCode, User

DASH = Path(__file__).resolve().parent.parent / "dashboard"
OLD, NEW = "old password 12345", "a brand new password 987"


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    limiter.reset()
    sent = []
    monkeypatch.setattr(mailer, "send_email", lambda session, **kw: sent.append(kw) or "id")
    monkeypatch.setattr(recovery, "send_in_background", lambda factory, to, subject, html, text: sent.append({"to": to, "subject": subject, "text": text, "html": html}))
    return sent


def make():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return Session(engine), engine


def user(s, login, admin=False, active=True):
    u = User(email=login, password_hash=hash_password(OLD), plan="sx_enterprise", requested_plan="sx_enterprise", is_admin=admin, active=active, approval_status="approved", full_name=login, organization="Org", must_change_password=True)
    s.add(u)
    s.commit()
    return u


def caller(engine):
    app = auth_application(lambda: Session(engine))

    def call(path, body=None, who=None, ip="1.1.1.1"):
        raw = json.dumps(body if body is not None else {}).encode()
        out = {}
        env = {"REQUEST_METHOD": "POST", "PATH_INFO": path, "QUERY_STRING": "", "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)), "REMOTE_ADDR": ip,
               "HTTP_AUTHORIZATION": ("Bearer " + issue_token(AuthIdentity(who.id, who.email, who.plan, who.is_admin))) if who else ""}
        res = app(env, lambda status, headers: out.update(status=status, headers=dict(headers)))
        return int(out["status"].split()[0]), json.loads(b"".join(res))
    return call


# ------------------------------------------------------------------------------------------------------------------------------ the codes
def test_codes_are_readable_random_and_stored_only_as_hashes():
    codes = {recovery.new_code() for _ in range(200)}
    assert len(codes) == 200 and all(len(c) == 14 and c[4] == "-" and c[9] == "-" and not set(c.replace("-", "")) & set("01OI") for c in codes)
    s, _ = make()
    u = user(s, "a@x.in")
    plain = recovery.make_backup_codes(s, u.id)
    rows = s.query(RecoveryCode).all()
    assert len(plain) == 8 and len(rows) == 8 and not {r.code_hash for r in rows} & set(plain) and all(len(r.code_hash) == 64 for r in rows)
    assert recovery.normalise("ab12-cd34 ef56") == "AB12CD34EF56"


def test_a_backup_code_resets_the_password_once_and_the_others_stay_valid():
    s, _ = make()
    u = user(s, "a@x.in")
    codes = recovery.make_backup_codes(s, u.id)
    recovery.reset_password(s, "a@x.in", codes[0].lower(), NEW)                                                    # case and dashes do not matter
    s.refresh(u)
    assert verify_password(NEW, u.password_hash) and not verify_password(OLD, u.password_hash) and u.must_change_password is False
    with pytest.raises(ValueError, match=recovery.NOT_VALID):
        recovery.reset_password(s, "a@x.in", codes[0], "another new password 1")                                   # used once
    recovery.reset_password(s, "a@x.in", codes[1], "another new password 1")                                       # the rest still work
    assert recovery.backup_status(s, u.id)["unused"] == 6


def test_new_backup_codes_replace_the_old_unused_ones():
    s, _ = make()
    u = user(s, "a@x.in")
    old = recovery.make_backup_codes(s, u.id)
    fresh = recovery.make_backup_codes(s, u.id)
    with pytest.raises(ValueError, match=recovery.NOT_VALID):
        recovery.reset_password(s, "a@x.in", old[0], NEW)
    recovery.reset_password(s, "a@x.in", fresh[0], NEW)


def test_every_failure_about_the_code_is_the_same_sentence_and_codes_belong_to_one_account():
    s, _ = make()
    a, b = user(s, "a@x.in"), user(s, "b@x.in")
    user(s, "off@x.in", active=False)
    ca = recovery.make_backup_codes(s, a.id)
    recovery.make_backup_codes(s, b.id)
    cases = [("a@x.in", "WRONG-CODE-HERE"), ("b@x.in", ca[0]), ("nobody@x.in", ca[0]), ("a@x.in", ""), ("off@x.in", ca[0])]
    for login, code in cases:
        with pytest.raises(ValueError) as e:
            recovery.reset_password(s, login, code, NEW)
        assert str(e.value) == recovery.NOT_VALID, (login, code)
    s.refresh(a)
    assert verify_password(OLD, a.password_hash)                                                                   # nothing changed
    for bad in ("short", "x" * 300, None):
        with pytest.raises(ValueError):
            recovery.reset_password(s, "a@x.in", ca[0], bad)


def test_an_e_mail_code_lasts_thirty_minutes_works_once_and_a_new_one_cancels_the_old():
    s, _ = make()
    u = user(s, "a@x.in")
    t0 = datetime.now(UTC)
    first = recovery.issue_email_code(s, "a@x.in", now=t0)[1]
    second = recovery.issue_email_code(s, "a@x.in", now=t0 + timedelta(minutes=1))[1]
    with pytest.raises(ValueError, match=recovery.NOT_VALID):
        recovery.reset_password(s, "a@x.in", first, NEW, now=t0 + timedelta(minutes=2))                            # cancelled by the newer one
    with pytest.raises(ValueError, match=recovery.NOT_VALID):
        recovery.reset_password(s, "a@x.in", second, NEW, now=t0 + timedelta(minutes=1 + recovery.EMAIL_CODE_MINUTES, seconds=1))   # expired
    third = recovery.issue_email_code(s, "a@x.in", now=t0)[1]
    recovery.reset_password(s, "a@x.in", third, NEW, now=t0 + timedelta(minutes=recovery.EMAIL_CODE_MINUTES - 1))
    s.refresh(u)
    assert verify_password(NEW, u.password_hash) and s.query(RecoveryCode).filter(RecoveryCode.kind == "email", RecoveryCode.used_at.is_(None)).count() == 0     # a successful reset leaves no live e-mail code behind


def test_only_accounts_with_an_e_mail_login_and_active_get_an_e_mail_code():
    s, _ = make()
    user(s, "plainname")
    user(s, "gone@x.in", active=False)
    assert recovery.issue_email_code(s, "plainname") is None and recovery.issue_email_code(s, "gone@x.in") is None and recovery.issue_email_code(s, "nobody@x.in") is None
    assert s.query(RecoveryCode).count() == 0


# ------------------------------------------------------------------------------------------------------------------------------ the routes
def test_forgot_answers_the_same_for_every_login_and_sends_mail_only_when_it_can(isolate):
    s, engine = make()
    user(s, "owner@x.in", admin=True)
    user(s, "username-only")
    call = caller(engine)
    answers = [call("/api/v1/auth/forgot", {"login": who}, ip=f"9.9.9.{i}") for i, who in enumerate(["owner@x.in", "nobody@x.in", "username-only"])]
    assert all(a == answers[0] for a in answers) and answers[0][0] == 200 and answers[0][1]["message"] == recovery.SENT
    assert len(isolate) == 1 and isolate[0]["to"] == "owner@x.in" and "Your code:" in isolate[0]["text"] and "forgot#login=owner@x.in&code=" in isolate[0]["text"]
    assert call("/api/v1/auth/forgot", {"login": "bad login with spaces"})[0] == 400


def test_the_whole_forgot_and_reset_flow_over_http_including_an_administrator(isolate):
    s, engine = make()
    admin = user(s, "owner@x.in", admin=True)
    call = caller(engine)
    call("/api/v1/auth/forgot", {"login": "owner@x.in"})
    code = next(l for l in isolate[0]["text"].splitlines() if l.startswith("Your code:")).split(": ", 1)[1]
    assert call("/api/v1/auth/reset", {"login": "owner@x.in", "code": "AAAA-BBBB-CCCC", "new_password": NEW})[0] == 400
    code_, body = call("/api/v1/auth/reset", {"login": "owner@x.in", "code": code, "new_password": NEW})
    assert code_ == 200 and "Password changed" in body["message"]
    status, login = call("/api/v1/auth/login", {"email": "owner@x.in", "password": NEW})
    assert status == 200 and login["account"]["is_admin"] is True and login["account"]["must_change_password"] is False
    assert call("/api/v1/auth/login", {"email": "owner@x.in", "password": OLD})[0] == 403
    assert call("/api/v1/auth/reset", {"login": "owner@x.in", "code": code, "new_password": "yet another long one 1"})[0] == 400       # the code was used
    s.refresh(admin)
    assert verify_password(NEW, admin.password_hash)


def test_guessing_is_limited_by_address_and_by_account():
    s, engine = make()
    user(s, "a@x.in")
    call = caller(engine)
    codes = [call("/api/v1/auth/reset", {"login": "a@x.in", "code": f"AAAA-BBBB-CC{i:02d}", "new_password": NEW}, ip="2.2.2.2")[0] for i in range(10)]
    assert codes[:8] == [400] * 8 and codes[8:] == [429, 429]                                                       # eight tries per address and account, then it stops
    other = [call("/api/v1/auth/reset", {"login": "a@x.in", "code": f"DDDD-EEEE-FF{i:02d}", "new_password": NEW}, ip=f"3.3.3.{i}")[0] for i in range(15)]
    assert other.count(400) == 12 and other.count(429) == 3                                                         # many addresses still hit the per-account ceiling (20 an hour)
    limiter.reset()
    forgot = [call("/api/v1/auth/forgot", {"login": "a@x.in"}, ip="4.4.4.4")[0] for _ in range(4)]
    assert forgot == [200, 200, 200, 429]


def test_backup_codes_need_a_signed_in_person_and_their_current_password():
    s, engine = make()
    u = user(s, "a@x.in")
    call = caller(engine)
    assert call("/api/v1/auth/recovery-codes", {"current_password": OLD})[0] == 401 and call("/api/v1/auth/recovery-status", {})[0] == 401
    assert call("/api/v1/auth/recovery-codes", {"current_password": "wrong"}, who=u)[0] == 403
    assert call("/api/v1/auth/recovery-codes", {}, who=u)[0] == 403
    assert call("/api/v1/auth/recovery-status", {}, who=u)[1] == {"unused": 0, "made_at": None, "email_possible": True}
    code, body = call("/api/v1/auth/recovery-codes", {"current_password": OLD}, who=u)
    assert code == 200 and len(body["codes"]) == 8 and "shown only now" in body["message"]
    status = call("/api/v1/auth/recovery-status", {}, who=u)[1]
    assert status["unused"] == 8 and status["made_at"] and "codes" not in status                                    # the codes are never shown again
    assert call("/api/v1/auth/reset", {"login": "a@x.in", "code": body["codes"][3], "new_password": NEW})[0] == 200
    off = user(s, "off@x.in", active=False)
    assert call("/api/v1/auth/recovery-status", {}, who=off)[0] == 401


def test_the_routes_refuse_other_methods_and_unknown_paths():
    s, engine = make()
    app = auth_application(lambda: Session(engine))
    out = {}
    list(app({"REQUEST_METHOD": "GET", "PATH_INFO": "/api/v1/auth/forgot", "wsgi.input": io.BytesIO(b""), "CONTENT_LENGTH": "0"}, lambda st, h: out.update(st=st)))
    assert out["st"].startswith("405")
    list(app({"REQUEST_METHOD": "POST", "PATH_INFO": "/api/v1/auth/unknown", "wsgi.input": io.BytesIO(b""), "CONTENT_LENGTH": "0"}, lambda st, h: out.update(st=st)))
    assert out["st"].startswith("404")


# ------------------------------------------------------------------------------------------------------------------------------ the server command, the pages
def test_the_server_command_sets_a_password_without_touching_anything_else():
    s, _ = make()
    u = user(s, "owner@x.in", admin=True)
    admin_reset.set_password(s, "OWNER@x.in", NEW)
    s.refresh(u)
    assert verify_password(NEW, u.password_hash) and u.is_admin and u.active and u.must_change_password is False
    with pytest.raises(ValueError):
        admin_reset.set_password(s, "owner@x.in", "short")
    with pytest.raises(LookupError):
        admin_reset.set_password(s, "nobody@x.in", NEW)


def test_the_pages_link_to_each_other_and_the_reset_page_stays_out_of_search():
    login, forgot, ws = (DASH / "login.html").read_text(encoding="utf-8"), (DASH / "forgot.html").read_text(encoding="utf-8"), (DASH / "workspace.html").read_text(encoding="utf-8")
    assert 'href="/forgot"' in login and 'name="robots" content="noindex"' in forgot and "/api/v1/auth/forgot" in forgot and "/api/v1/auth/reset" in forgot and 'href="/login"' in forgot
    assert "/api/v1/auth/recovery-codes" in ws and 'id="rcdlg"' in ws and 'id="rcopen"' in ws
    from api import services_cms
    assert "Disallow: /forgot" in services_cms.robots_txt()


def test_the_web_app_serves_the_forgot_page_and_the_new_routes_without_login():
    import web
    out = {}
    res = web.application({"REQUEST_METHOD": "GET", "PATH_INFO": "/forgot", "QUERY_STRING": "", "REMOTE_ADDR": "127.0.0.1"}, lambda st, h: out.update(st=st))
    assert out["st"].startswith("200") and b"Set the new password" in b"".join(res)
    raw = json.dumps({"login": "nobody-here@example.org"}).encode()
    res = web.application({"REQUEST_METHOD": "POST", "PATH_INFO": "/api/v1/auth/forgot", "QUERY_STRING": "", "REMOTE_ADDR": "127.0.0.9", "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw))}, lambda st, h: out.update(st=st))
    assert out["st"].startswith("200") and json.loads(b"".join(res))["message"] == recovery.SENT


def test_the_workspace_script_still_parses():
    """A broken string in the page script once left the whole workspace blank; Node (when present) checks the syntax of the big inline script."""
    import re
    import shutil
    import subprocess
    import tempfile
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = max(re.findall(r"<script>(.*?)</script>", (DASH / "workspace.html").read_text(encoding="utf-8"), re.S), key=len)
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "ws.js"
        path.write_text(script, encoding="utf-8")
        done = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[:500]
    for name in ("cms.js", "surveys.js", "social.js", "market.js", "me.js"):
        done = subprocess.run([node, "--check", str(DASH / name)], capture_output=True, text=True)
        assert done.returncode == 0, (name, done.stderr[:300])


def test_two_workers_creating_a_new_table_at_once_do_not_crash_the_second(monkeypatch):
    """On the first start after a release adds a table, both web workers may try to create it; the one that loses must try again, not die."""
    import collector.storage as storage
    real, calls = storage.Base.metadata.create_all, []

    def flaky(engine, *a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise storage.IntegrityError("create", {}, Exception("duplicate key value violates unique constraint pg_type_typname_nsp_index"))
        return real(engine, *a, **k)
    monkeypatch.setattr(storage.Base.metadata, "create_all", flaky)
    monkeypatch.setattr(storage.time, "sleep", lambda s: None)
    storage.create_database("sqlite://")
    assert len(calls) == 2
