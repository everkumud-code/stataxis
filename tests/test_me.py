"""A person's own account: the screens they may use and chose, the first-sign-in choice, the forced password change and the profile."""
import io
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import feature_access, me, user_admin
from api.auth import AuthIdentity, hash_password, issue_token, verify_password
from api.auth_service import change_password, login
from api.gate import gate_application
from api.me_http import me_application
from collector.storage import Base, User


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")


@pytest.fixture
def world():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = Session(engine)
    users = {}
    for key, plan, admin in (("free", "sx_free", False), ("idea", "sx_idea", False), ("analyst", "sx_analyst", False), ("boss", "sx_enterprise", True)):
        u = User(email=f"{key}@x.com", password_hash=hash_password("x" * 14), plan=plan, is_admin=admin, active=True, approval_status="approved", full_name=key.title(), organization="Org " + key)
        s.add(u)
        users[key] = u
    s.commit()
    return s, engine, users


def test_a_new_free_login_sees_the_basics_only_and_the_package_decides_the_rest(world):
    s, _, u = world
    free = me.nav_views(s, u["free"])
    assert set(free) == {"briefing", "overview", "market", "channel", "stx"}
    idea = set(me.nav_views(s, u["idea"]))
    assert idea > set(free) and {"dashboard", "weekly", "primetime", "builder", "content", "trends", "changed", "evaluate", "stream"} <= idea and not {"planner", "live", "authenticity", "creators", "audience"} & idea
    analyst = set(me.nav_views(s, u["analyst"]))
    assert {"planner", "audience", "live", "competition", "research", "creators", "liveevent"} <= analyst and "authenticity" not in analyst
    assert set(me.nav_views(s, u["boss"])) == {v[0] for v in me.VIEWS}


def test_an_administrators_tick_adds_or_removes_one_screen_for_one_person(world):
    s, _, u = world
    feature_access.set_user_feature(s, u["free"].id, "planner", True, "boss@x.com")
    feature_access.set_user_feature(s, u["free"].id, "market", False, "boss@x.com")
    nav = me.nav_views(s, u["free"])
    assert "planner" in nav and "market" not in nav and "briefing" in nav


def test_the_first_choice_narrows_the_menu_to_what_is_relevant_and_never_adds_what_is_not_allowed(world):
    s, _, u = world
    assert me.me_payload(s, u["analyst"])["preferences"]["onboarded"] is False
    out = me.set_preferences(s, u["analyst"], {"persona": "buyer", "languages": ["Hindi"], "segments": ["news"], "start_view": "planner"})
    assert out["preferences"]["onboarded"] is True and out["start_view"] == "planner"
    assert set(out["nav"]) == {"briefing", "market", "channel", "stx", "weekly", "primetime", "planner", "audience", "builder", "liveevent"}     # the buyer's set, minus what this package lacks (the authenticity radar)
    out = me.set_preferences(s, u["analyst"], {"persona": "buyer", "views": ["planner", "creators", "live"], "start_view": "profile"})
    assert out["nav"] == ["live", "creators", "planner"] and out["start_view"] == "profile"
    chosen_but_not_allowed = me.set_preferences(s, u["free"], {"views": ["planner", "authenticity"]})
    assert chosen_but_not_allowed["nav"] == ["briefing", "overview", "market", "channel", "stx"]     # nothing allowed was chosen: the person sees what they may use, never an empty menu
    assert me.set_preferences(s, u["free"], {"persona": None, "views": None})["nav"] == ["briefing", "overview", "market", "channel", "stx"]


@pytest.mark.parametrize("body", [{"persona": "king"}, {"views": ["nope"]}, {"views": "weekly"}, {"languages": ["Klingon"]}, {"segments": ["xyz"]}, {"start_view": "nowhere"}])
def test_preferences_refuse_anything_that_is_not_on_the_lists(world, body):
    s, _, u = world
    with pytest.raises(ValueError):
        me.set_preferences(s, u["free"], body)


def test_the_profile_changes_only_what_a_person_may_change(world):
    s, _, u = world
    out = me.update_profile(s, u["free"], {"full_name": "  Asha Rao ", "mobile": "+91 98765-43210", "job_title": "Planner"})
    assert out["account"]["full_name"] == "Asha Rao" and out["account"]["mobile"] == "+91 98765-43210" and out["account"]["job_title"] == "Planner"
    assert out["account"]["email"] == "free@x.com" and out["account"]["plan"] == "sx_free" and out["account"]["organization"] == "Org free"
    for bad in ({"full_name": ""}, {"full_name": "x" * 300}, {"full_name": "A", "mobile": "call me"}, {"full_name": "A", "job_title": "t" * 200}):
        with pytest.raises(ValueError):
            me.update_profile(s, u["free"], bad)


def test_an_account_made_or_reset_by_an_administrator_must_choose_its_own_password(world):
    s, _, u = world
    made = user_admin.create_user(s, email="newbie", name="New Person", organization="Firm", mobile="", plan="sx_free")
    new = s.get(User, made["id"])
    assert new.must_change_password is True and made["must_change_password"] is True and login(s, "newbie", made["temporary_password"])["account"]["must_change_password"] is True
    change_password(s, new.id, made["temporary_password"], "a brand new password 123")
    assert new.must_change_password is False and verify_password("a brand new password 123", new.password_hash)
    again = user_admin.reset_password(s, new.id)
    assert s.get(User, new.id).must_change_password is True and "choose their own password" in again["note"]
    assert u["boss"].must_change_password in (False, None) and u["free"].must_change_password in (False, None)


def _downstream(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [b"passed"]


def _call(app, method, path, who):
    out = {}
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "wsgi.input": io.BytesIO(b""), "CONTENT_LENGTH": "0", "REMOTE_ADDR": "127.0.0.1",
               "HTTP_AUTHORIZATION": ("Bearer " + issue_token(AuthIdentity(who.id, who.email, who.plan, who.is_admin))) if who else ""}
    res = app(environ, lambda status, headers: out.update(status=status))
    body = b"".join(res)
    return int(out["status"].split()[0]), body


def test_the_gate_refuses_the_screens_with_data_of_their_own_to_those_who_may_not_use_them(world):
    s, engine, u = world
    gate = gate_application(lambda: Session(engine), _downstream)
    assert _call(gate, "GET", "/api/v1/operations/collection", u["analyst"])[0] == 403 and _call(gate, "GET", "/api/v1/operations/collection", u["boss"]) == (200, b"passed")
    assert _call(gate, "GET", "/api/v1/audience/live", u["free"])[0] == 403 and _call(gate, "GET", "/api/v1/audience/live", u["analyst"])[0] == 200
    assert _call(gate, "POST", "/api/v1/evaluate/youtube", u["free"])[0] == 403 and _call(gate, "POST", "/api/v1/evaluate/youtube", u["idea"])[0] == 200
    assert _call(gate, "GET", "/api/v1/reports/export", u["idea"])[0] == 403 and _call(gate, "GET", "/api/v1/reports/export", u["analyst"])[0] == 200
    assert _call(gate, "GET", "/api/v1/insights/what-changed", u["free"])[0] == 200 and _call(gate, "GET", "/api/v1/insights/what-changed", u["free"]) [1] == b"passed"   # overview is basic
    feature_access.set_user_feature(s, u["analyst"].id, "live", False, "boss@x.com")
    assert _call(gate, "GET", "/api/v1/audience/live", u["analyst"])[0] == 403
    assert _call(gate, "GET", "/api/v1/channels", u["free"]) == (200, b"passed") and _call(gate, "GET", "/api/v1/channels", None) == (200, b"passed")   # no sign-in: the API itself says 401


def test_until_the_password_is_changed_nothing_but_who_am_i_works(world):
    s, engine, u = world
    gate = gate_application(lambda: Session(engine), _downstream)
    u["idea"].must_change_password = True
    s.commit()
    for method, path in (("GET", "/api/v1/channels"), ("GET", "/api/v1/market/weekly"), ("POST", "/api/v1/my/channels/claim"), ("POST", "/api/v1/me/preferences"), ("GET", "/api/v1/admin/users/list")):
        code, body = _call(gate, method, path, u["idea"])
        assert code == 403 and json.loads(body)["code"] == "password_change_required", path
    assert _call(gate, "GET", "/api/v1/me", u["idea"]) == (200, b"passed")
    change_password(s, u["idea"].id, "x" * 14, "a different password 1234")
    assert _call(gate, "GET", "/api/v1/channels", u["idea"]) == (200, b"passed")


def test_the_http_routes_for_my_account(world):
    s, engine, u = world
    app = me_application(lambda: Session(engine))

    def call(method, path, who, body=None):
        raw = json.dumps(body or {}).encode()
        out = {}
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)) if method == "POST" else "0",
                   "HTTP_AUTHORIZATION": ("Bearer " + issue_token(AuthIdentity(who.id, who.email, who.plan, who.is_admin))) if who else ""}
        res = app(environ, lambda status, headers: out.update(status=status))
        return int(out["status"].split()[0]), json.loads(b"".join(res))

    assert call("GET", "/api/v1/me", None)[0] == 401
    status, body = call("GET", "/api/v1/me", u["idea"])
    assert status == 200 and body["account"]["email"] == "idea@x.com" and body["preferences"]["onboarded"] is False and body["must_change_password"] is False
    assert {"overview", "weekly"} <= set(body["nav"]) and "planner" not in body["nav"] and len(body["personas"]) == 5 and body["start_view"] == body["nav"][0]
    status, body = call("POST", "/api/v1/me/preferences", u["idea"], {"persona": "media", "start_view": "weekly"})
    assert status == 200 and body["preferences"]["onboarded"] is True and body["start_view"] == "weekly" and "planner" not in body["nav"]
    assert call("POST", "/api/v1/me/preferences", u["idea"], {"persona": "king"})[0] == 400
    assert call("POST", "/api/v1/me/profile", u["idea"], {"full_name": "Idea Person", "job_title": "Buyer"})[1]["account"]["job_title"] == "Buyer"
    assert call("POST", "/api/v1/me/profile", u["idea"], {"full_name": ""})[0] == 400
    other = call("GET", "/api/v1/me", u["free"])[1]
    assert other["preferences"]["persona"] is None and other["account"]["full_name"] == "Free"   # one person's choices are not another's
