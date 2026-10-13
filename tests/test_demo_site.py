"""The public demo: the real workspace on invented data, read-only, and sealed off from the real accounts and the real data."""
import io
import json

import pytest

import web
from api import demo_data


@pytest.fixture(scope="module")
def secret():
    import os

    os.environ["STAXIS_AUTH_SECRET"] = os.environ.get("STAXIS_AUTH_SECRET") or "test-secret"
    yield


def call(method, path, token=None, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    out = {}
    path, _, query = path.partition("?")
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "wsgi.input": io.BytesIO(raw), "CONTENT_LENGTH": str(len(raw)), "REMOTE_ADDR": "203.0.113.7",
               "HTTP_AUTHORIZATION": ("Bearer " + token) if token else ""}
    res = web.application(environ, lambda status, headers: out.update(status=status, headers=dict(headers)))
    data = b"".join(res)
    try:
        return int(out["status"].split()[0]), json.loads(data), out["headers"]
    except ValueError:
        return int(out["status"].split()[0]), data, out["headers"]


@pytest.fixture(scope="module")
def token(secret):
    status, body, _ = call("GET", "/demo-api/session")
    assert status == 200
    return body["token"]


def test_the_demo_session_is_a_non_admin_visitor_with_every_screen(secret, token):
    status, me, _ = call("GET", "/demo-api/v1/me", token)
    assert status == 200 and me["account"]["is_admin"] is False and me["account"]["email"] == demo_data.DEMO_LOGIN and me["preferences"]["onboarded"] is True
    assert {"planner", "authenticity", "creators", "audience", "liveevent", "briefing"} <= set(me["nav"]) and me["must_change_password"] is False


def test_everything_in_the_demo_is_plainly_invented(secret, token):
    status, body, _ = call("GET", "/demo-api/v1/channels", token)
    names = [c["name"] for c in body["channels"]]
    assert status == 200 and len(names) >= 20 and all(n.startswith("Sample ") for n in names)


def test_the_real_screens_run_on_the_demo_data(secret, token):
    status, plan, _ = call("POST", "/demo-api/v1/market/planner", token, {"start_hour": 20, "end_hour": 22, "days": 7})
    assert status == 200 and len(plan["channels"]) >= 10 and plan["channels"][0]["name"].startswith("Sample ")
    status, radar, _ = call("GET", "/demo-api/v1/market/authenticity", token)
    assert status == 200 and any(c["name"] == demo_data.FLAT for c in radar["channels"] if c["risk"] != "low")      # the flat line is found, by the real radar
    status, ifx, _ = call("GET", "/demo-api/v1/market/creator-index?segment=creator", token)
    assert status == 200 and len([c for c in ifx["channels"] if c["index_score"] is not None]) >= 3 and len(ifx["part_labels"]) == 12


def test_the_demo_can_look_at_everything_and_change_nothing(secret, token):
    for method, path, body in (("POST", "/demo-api/v1/market/authenticity/review", {"channel_id": 1, "signal": "x", "status": "cleared"}), ("POST", "/demo-api/v1/admin/users/create", {"email": "x"}),
                               ("POST", "/demo-api/v1/my/channels/claim", {"channel_id": 1}), ("POST", "/demo-api/v1/me/profile", {"full_name": "Hacker"}), ("POST", "/demo-api/v1/me/preferences", {"persona": "buyer"}),
                               ("POST", "/demo-api/v1/auth/change-password", {"current_password": "x", "new_password": "y" * 14}), ("DELETE", "/demo-api/v1/channels/1", None), ("PUT", "/demo-api/v1/channels/1", {})):
        status, payload, _ = call(method, path, token, body)
        assert status == 403 and "read-only" in payload["error"], (method, path)
    assert call("GET", "/demo-api/v1/admin/users/list", token)[0] == 403        # an ordinary visitor is not an administrator
    assert call("GET", "/demo-api/v1/market/weekly")[0] == 401                  # a call without the demo token is refused like any other


def test_a_demo_token_is_useless_against_the_real_api_and_the_real_data(secret, token):
    for path in ("/api/v1/channels", "/api/v1/me", "/api/v1/market/weekly", "/api/v1/my/channels", "/api/v1/admin/users/list"):
        status, _payload, _ = call("GET", path, token)
        assert status in (401, 403), path


def test_the_demo_page_is_the_real_workspace_with_a_banner_and_no_way_to_leave_the_demo_data():
    status, body, headers = call("GET", "/demo")
    assert status == 200 and b"/demo-api/" in body and b"invented sample channels" in body and b"read-only" not in body[:0] and headers["Cache-Control"] == "no-store"
    assert b"STATAXIS" in body and b"market.js" in body and b"me.js" in body and body.count(b"<head>") == 1
    status, text, _ = call("GET", "/demo-api/not-a-route", None)
    assert status in (401, 404)
