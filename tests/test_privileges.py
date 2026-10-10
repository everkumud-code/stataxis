"""Per-person privileges (the tick boxes) and the machine-readable export as its own privilege."""
import io
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import feature_access
from api.admin_http import admin_application
from api.auth import AuthIdentity, issue_token
from api.live_http import live_application
from api.market_http import market_application
from collector.storage import Base, User, UserFeatureOverride


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")


def make():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = Session(engine)
    for uid, email, plan, admin in ((1, "idea@x.com", "sx_idea", False), (2, "pro@x.com", "sx_pro", False), (3, "boss@x.com", "sx_enterprise", True), (4, "analyst@x.com", "sx_analyst", False)):
        s.add(User(id=uid, email=email, password_hash="x", plan=plan, is_admin=admin, active=True, approval_status="approved", full_name=email.split("@")[0]))
    s.commit()
    return s, engine


def test_the_tick_wins_over_the_package_and_removing_it_goes_back():
    s, _ = make()
    idea = s.get(User, 1)
    rows = {r["feature"]: r for r in feature_access.user_matrix(s, idea)}
    assert rows["weekly"]["allowed"] and rows["weekly"]["source"] == "package" and not rows["planner"]["allowed"] and not rows["planner"]["by_package"]
    assert set(rows) == set(feature_access.FEATURES) and all(r["description"] for r in rows.values())
    feature_access.set_user_feature(s, 1, "planner", True, "boss@x.com")        # a tick for one person
    feature_access.set_user_feature(s, 1, "weekly", False, "boss@x.com")        # and a tick taken away
    rows = {r["feature"]: r for r in feature_access.user_matrix(s, idea)}
    assert rows["planner"]["allowed"] and rows["planner"]["source"] == "admin" and rows["planner"]["set_by"] == "boss@x.com" and not rows["planner"]["by_package"]
    assert not rows["weekly"]["allowed"] and rows["weekly"]["by_package"] and rows["weekly"]["source"] == "admin"
    assert feature_access.allowed(s, "planner", "sx_idea", False, 1) and not feature_access.allowed(s, "weekly", "sx_idea", False, 1)
    assert not feature_access.allowed(s, "planner", "sx_idea", False, 99)         # somebody else is unaffected
    assert "switched off for your account" in feature_access.explain_denied(s, "weekly", "sx_idea", 1)
    feature_access.set_user_feature(s, 1, "planner", None, "boss@x.com")
    feature_access.set_user_feature(s, 1, "weekly", None, "boss@x.com")
    assert s.query(UserFeatureOverride).count() == 0 and not feature_access.allowed(s, "planner", "sx_idea", False, 1) and feature_access.allowed(s, "weekly", "sx_idea", False, 1)


def test_an_administrator_has_everything_and_bad_input_is_refused():
    s, _ = make()
    assert all(r["allowed"] for r in feature_access.user_matrix(s, s.get(User, 3)))
    with pytest.raises(ValueError, match="administrator"):
        feature_access.set_user_feature(s, 3, "weekly", False, "x")
    with pytest.raises(ValueError):
        feature_access.set_user_feature(s, 1, "nothing", True, "x")
    with pytest.raises(LookupError):
        feature_access.set_user_feature(s, 999, "weekly", True, "x")
    feature_access.set_user_feature(s, 1, "weekly", False, "x")
    feature_access.set_user_feature(s, 1, "weekly", False, "y")                  # setting it again changes who set it, it does not pile up
    assert s.query(UserFeatureOverride).count() == 1 and s.query(UserFeatureOverride).one().set_by == "y"


def call(app, method, path, user, query="", body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    out = {}
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)),
               "HTTP_AUTHORIZATION": "Bearer " + issue_token(AuthIdentity(user.id, user.email, user.plan, user.is_admin))}
    res = app(environ, lambda status, headers: out.update(status=status, headers=dict(headers)))
    return int(out["status"].split()[0]), (json.loads(res[0]) if res[0][:1] == b"{" else res[0]), out["headers"]


def test_a_tick_opens_or_closes_a_tool_at_once_over_http():
    s, engine = make()
    market = market_application(lambda: Session(engine))
    idea, pro, boss = s.get(User, 1), s.get(User, 2), s.get(User, 3)
    admin = admin_application(lambda: Session(engine))
    assert call(market, "GET", "/api/v1/market/creators", idea)[0] == 403                    # SX Intelligence and above
    status, body, _ = call(admin, "POST", "/api/v1/admin/users/features/set", boss, body={"user_id": 1, "feature": "creators", "allowed": True})
    assert status == 200 and next(f for f in body["features"] if f["feature"] == "creators")["allowed"]
    assert call(market, "GET", "/api/v1/market/creators", idea)[0] == 200                    # same login, now allowed
    call(admin, "POST", "/api/v1/admin/users/features/set", boss, body={"user_id": 2, "feature": "authenticity", "allowed": False})
    status, body, _ = call(market, "GET", "/api/v1/market/authenticity", pro)
    assert status == 403 and "switched off for your account" in body["error"]
    call(admin, "POST", "/api/v1/admin/users/features/set", boss, body={"user_id": 2, "feature": "authenticity", "allowed": None})
    assert call(market, "GET", "/api/v1/market/authenticity", pro)[0] == 200                 # back to the package
    status, body, _ = call(admin, "POST", "/api/v1/admin/users/features", boss, body={"user_id": 1})
    assert status == 200 and body["user"]["email"] == "idea@x.com" and len(body["features"]) == len(feature_access.FEATURES) and len(body["plans"]) == 7
    assert call(admin, "POST", "/api/v1/admin/users/features/set", boss, body={"user_id": 1, "feature": "creators", "allowed": "yes"})[0] == 400
    assert call(admin, "POST", "/api/v1/admin/users/features", idea, body={"user_id": 2})[0] == 403
    assert call(admin, "POST", "/api/v1/admin/users/features/set", boss, body={"user_id": 3, "feature": "weekly", "allowed": False})[0] == 400


def test_the_excel_export_is_its_own_privilege():
    s, engine = make()
    live = live_application(lambda: Session(engine))
    admin = admin_application(lambda: Session(engine))
    boss, idea, analyst = s.get(User, 3), s.get(User, 1), s.get(User, 4)
    q = f"start={datetime(2026, 10, 1, tzinfo=UTC).isoformat().replace('+', '%2B')}&end={datetime(2026, 10, 1, 1, tzinfo=UTC).isoformat().replace('+', '%2B')}"
    status, body, _ = call(live, "GET", "/api/v1/audience/live/export", idea, query=q)
    assert status == 403 and "Excel data exports" in body["error"]                          # SX Idea can read reports but not take the raw numbers away
    status, body, headers = call(live, "GET", "/api/v1/audience/live/export", analyst, query=q)
    assert status == 200 and body[:2] == b"PK" and "spreadsheetml" in headers["Content-Type"]
    call(admin, "POST", "/api/v1/admin/users/features/set", boss, body={"user_id": 1, "feature": "data_export", "allowed": True})
    assert call(live, "GET", "/api/v1/audience/live/export", idea, query=q)[0] == 200       # an admin tick opens it for one person
    call(admin, "POST", "/api/v1/admin/users/features/set", boss, body={"user_id": 4, "feature": "data_export", "allowed": False})
    assert call(live, "GET", "/api/v1/audience/live/export", analyst, query=q)[0] == 403    # and an un-tick closes it for another
    s.get(User, 1).active = False
    s.commit()
    assert call(live, "GET", "/api/v1/audience/live/export", idea, query=q)[0] == 401       # switched off: nothing works
