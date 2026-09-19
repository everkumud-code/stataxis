import io
import json

import web
from api.errors import AuthenticationError, AuthorizationError
from api.live_http import live_application


class _Session:
    def close(self):
        pass


def _call(app, path, authorization=None):
    captured = {}
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
    }
    if authorization is not None:
        environ["HTTP_AUTHORIZATION"] = authorization
    body = app(environ, lambda status, headers: captured.update(status=status, headers=headers))
    return captured["status"], captured["headers"], body[0]


def test_web_routes_live_export_and_live_paths_exactly(monkeypatch):
    calls = []

    def fake_live_api(environ, start_response):
        calls.append(environ["PATH_INFO"])
        start_response("418 I'm a teapot", [("Content-Type", "text/plain")])
        return [b"routed"]

    monkeypatch.setattr(web, "_live_api", fake_live_api)

    for path in (
        "/api/v1/audience/live/export",
        "/api/v1/audience/live",
        "/api/v1/evaluate/youtube/live-sample",
    ):
        status, _, body = _call(web.application, path)
        assert status == "418 I'm a teapot"
        assert body == b"routed"

    status, _, _ = _call(web.application, "/api/v1/audience/live/export/extra")
    assert status == "401 Unauthorized"
    assert calls == [
        "/api/v1/audience/live/export",
        "/api/v1/audience/live",
        "/api/v1/evaluate/youtube/live-sample",
    ]


def test_live_export_no_token_is_401(monkeypatch):
    def fake_auth(_authorization):
        raise AuthenticationError("authentication required")

    monkeypatch.setattr("api.live_http.authenticate", fake_auth)
    app = live_application(lambda: _Session())

    status, _, body = _call(app, "/api/v1/audience/live/export")
    assert status == "401 Unauthorized"
    assert json.loads(body) == {"error": "authentication required"}


def test_live_export_free_plan_is_403(monkeypatch):
    monkeypatch.setattr("api.live_http.authenticate", lambda _authorization: object())

    def deny(_policy, _capability):
        raise AuthorizationError("premium access required")

    monkeypatch.setattr("api.live_http.policy_for_identity", lambda _identity: object())
    monkeypatch.setattr("api.live_http.require_capability", deny)
    app = live_application(lambda: _Session())

    status, _, body = _call(app, "/api/v1/audience/live/export", "Bearer free")
    assert status == "403 Forbidden"
    assert json.loads(body) == {"error": "premium access required"}


def test_live_export_premium_plan_is_200_xlsx(monkeypatch):
    monkeypatch.setattr("api.live_http.authenticate", lambda _authorization: object())
    monkeypatch.setattr("api.live_http.policy_for_identity", lambda _identity: object())
    monkeypatch.setattr("api.live_http.require_capability", lambda _policy, _capability: None)
    monkeypatch.setattr("api.live_http.export_live_audience_xlsx", lambda *args, **kwargs: b"PK\x03\x04xlsx")
    app = live_application(lambda: _Session())

    status, headers, body = _call(app, "/api/v1/audience/live/export", "Bearer premium")
    assert status == "200 OK"
    assert dict(headers)["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert body.startswith(b"PK")
