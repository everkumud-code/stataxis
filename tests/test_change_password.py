"""A signed-in account can change its own password: the current one must be proven, the new one must be strong and different, and the old one stops working."""
import io
import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from api.auth import AuthIdentity, hash_password, issue_token
from api.auth_http import auth_application
from api.auth_service import change_password, login
from api.rate_limit import limiter
from collector.storage import User, create_database

OLD = "correct horse battery"
NEW = "a brand new passphrase"


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    limiter.reset()
    yield
    limiter.reset()


def make(tmp_path):
    engine = create_database(f"sqlite:///{tmp_path / 'pw.db'}")
    session = Session(engine)
    user = User(email="admin@example.com", password_hash=hash_password(OLD), plan="sx_enterprise", is_admin=True, active=True, approval_status="approved")
    session.add(user)
    session.commit()
    return engine, session, user


def test_change_password_replaces_the_hash_and_the_old_password_stops_working(tmp_path):
    _, session, user = make(tmp_path)
    before = user.password_hash
    change_password(session, user.id, OLD, NEW)
    session.refresh(user)
    assert user.password_hash != before and NEW not in user.password_hash
    assert login(session, "admin@example.com", NEW)["account"]["email"] == "admin@example.com"
    with pytest.raises(PermissionError):
        login(session, "admin@example.com", OLD)


def test_wrong_current_password_changes_nothing(tmp_path):
    _, session, user = make(tmp_path)
    before = user.password_hash
    with pytest.raises(PermissionError, match="current password is not correct"):
        change_password(session, user.id, "not the password", NEW)
    session.refresh(user)
    assert user.password_hash == before


@pytest.mark.parametrize("new,msg", [("short one", "at least 12"), (OLD, "different"), ("x" * 300, "too long")])
def test_weak_or_unchanged_new_password_is_refused(tmp_path, new, msg):
    _, session, user = make(tmp_path)
    with pytest.raises(ValueError, match=msg):
        change_password(session, user.id, OLD, new)


def _call(app, token, payload):
    body = json.dumps(payload).encode()
    out = {}
    environ = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/v1/auth/change-password", "REMOTE_ADDR": "127.0.0.1", "wsgi.input": io.BytesIO(body), "CONTENT_LENGTH": str(len(body))}
    if token:
        environ["HTTP_AUTHORIZATION"] = "Bearer " + token
    result = app(environ, lambda status, headers: out.update(status=status))
    return out["status"], json.loads(result[0])


def test_endpoint_needs_a_signed_in_user_and_changes_only_that_users_password(tmp_path):
    engine, session, user = make(tmp_path)
    other = User(email="other@example.com", password_hash=hash_password("other person passphrase"), plan="sx_free", approval_status="approved")
    session.add(other)
    session.commit()
    app = auth_application(lambda: Session(engine))
    assert _call(app, "", {"current_password": OLD, "new_password": NEW})[0].startswith("401")
    assert _call(app, "garbage.token", {"current_password": OLD, "new_password": NEW})[0].startswith("401")
    token = issue_token(AuthIdentity(user.id, user.email, user.plan, True))
    status, body = _call(app, token, {"current_password": OLD, "new_password": NEW})
    assert status.startswith("200") and body == {"message": "Password changed."}
    fresh = Session(engine)
    assert login(fresh, "admin@example.com", NEW)
    assert login(fresh, "other@example.com", "other person passphrase")
    with pytest.raises(PermissionError):
        login(fresh, "admin@example.com", OLD)


def test_endpoint_reports_a_wrong_current_password_and_bad_input_in_plain_words(tmp_path):
    engine, _, user = make(tmp_path)
    app = auth_application(lambda: Session(engine))
    token = issue_token(AuthIdentity(user.id, user.email, user.plan, True))
    status, body = _call(app, token, {"current_password": "nope nope nope", "new_password": NEW})
    assert status.startswith("403") and body["error"] == "current password is not correct"
    status, body = _call(app, token, {"current_password": OLD, "new_password": "tiny"})
    assert status.startswith("400") and "12 characters" in body["error"]
    status, body = _call(app, token, {"current_password": OLD})
    assert status.startswith("400")


def test_endpoint_is_rate_limited_per_user(tmp_path):
    engine, _, user = make(tmp_path)
    app = auth_application(lambda: Session(engine))
    token = issue_token(AuthIdentity(user.id, user.email, user.plan, True))
    for _ in range(5):
        assert _call(app, token, {"current_password": "nope nope nope", "new_password": NEW})[0].startswith("403")
    assert _call(app, token, {"current_password": OLD, "new_password": NEW})[0].startswith("429")


def test_workspace_has_the_change_password_button_and_dialog():
    html = (Path(__file__).resolve().parent.parent / "dashboard" / "workspace.html").read_text(encoding="utf-8")
    for needle in ('id="chpw"', 'id="pwdlg"', "/api/v1/auth/change-password", "current_password", "new_password"):
        assert needle in html
