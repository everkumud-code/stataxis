import io
import json

from api.auth_http import auth_application
from api.rate_limit import limiter


class Session:
    def close(self):
        pass


def _request(app, path, payload, forwarded):
    body = json.dumps(payload).encode()
    captured = {}
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "REMOTE_ADDR": "127.0.0.1",
        "HTTP_X_FORWARDED_FOR": forwarded,
        "wsgi.input": io.BytesIO(body),
        "CONTENT_LENGTH": str(len(body)),
    }
    result = app(environ, lambda status, headers: captured.update(status=status, headers=dict(headers)))
    return captured, json.loads(result[0])


def test_login_rate_limit_is_per_ip_and_email_with_retry_after(monkeypatch):
    limiter.reset()
    monkeypatch.setattr("api.auth_http.login", lambda *args: {"ok": True})
    app = auth_application(lambda: Session())
    payload = {"email": "user@example.com", "password": "correct horse battery"}
    for _ in range(10):
        captured, _ = _request(app, "/api/v1/auth/login", payload, "203.0.113.10, 10.0.0.1")
        assert captured["status"] == "200 OK"
    captured, body = _request(app, "/api/v1/auth/login", payload, "203.0.113.10, 10.0.0.1")
    assert captured["status"] == "429 Too Many Requests"
    assert int(captured["headers"]["Retry-After"]) > 0
    assert body == {"error": "too many requests"}
    captured, _ = _request(app, "/api/v1/auth/login", payload, "203.0.113.11")
    assert captured["status"] == "200 OK"
    limiter.reset()


def test_register_rate_limit_is_per_ip_with_retry_after(monkeypatch):
    limiter.reset()
    monkeypatch.setattr("api.auth_http.register", lambda *args: {"id": 1})
    app = auth_application(lambda: Session())
    payload = {
        "email": "user@example.com",
        "password": "correct horse battery",
        "name": "Test User",
        "mobile": "+91-9000000000",
        "organization": "Example Media Pvt Ltd",
        "purpose_of_use": "Testing",
        "requested_plan": "sx_free",
    }
    for _ in range(5):
        captured, _ = _request(app, "/api/v1/auth/register", payload, "203.0.113.20")
        assert captured["status"] == "201 Created"
    captured, body = _request(app, "/api/v1/auth/register", payload, "203.0.113.20")
    assert captured["status"] == "429 Too Many Requests"
    assert int(captured["headers"]["Retry-After"]) > 0
    assert body == {"error": "too many requests"}
    captured, _ = _request(app, "/api/v1/auth/register", payload, "203.0.113.21")
    assert captured["status"] == "201 Created"
    limiter.reset()


def test_duplicate_registration_returns_generic_success(monkeypatch):
    limiter.reset()
    monkeypatch.setattr("api.auth_http.register", lambda *args: {"already_exists": True})
    app = auth_application(lambda: Session())
    payload = {
        "email": "existing@example.com",
        "password": "correct horse battery",
        "name": "Test User",
        "mobile": "+91-9000000000",
        "organization": "Example Media Pvt Ltd",
        "purpose_of_use": "Testing",
        "requested_plan": "sx_free",
    }
    captured, body = _request(app, "/api/v1/auth/register", payload, "203.0.113.30")
    assert captured["status"] == "201 Created"
    assert body == {"message": "Profile submitted for admin approval."}
    limiter.reset()
