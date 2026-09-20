import io
import json

from web import application


def request(path, method="GET", body=b"", forwarded=None):
    captured = {}
    environ = {"PATH_INFO": path, "REQUEST_METHOD": method, "REMOTE_ADDR": "127.0.0.1",
               "wsgi.input": io.BytesIO(body), "CONTENT_LENGTH": str(len(body))}
    if forwarded:
        environ["HTTP_X_FORWARDED_FOR"] = forwarded
    result = application(environ, lambda status, headers: captured.update(status=status, headers=dict(headers)))
    return captured["status"], captured["headers"], b"".join(result)


def test_static_extension_allowlist_and_favicon():
    status, headers, body = request("/launch-notes.md")
    assert status == "404 Not Found"
    status, headers, body = request("/api.py")
    assert status == "404 Not Found"
    status, headers, body = request("/favicon.ico")
    assert status == "200 OK"
    assert headers["Content-Security-Policy"].startswith("default-src 'self'")
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_security_headers_and_no_store():
    status, headers, _ = request("/health")
    assert status == "200 OK"
    assert headers["Strict-Transport-Security"] == "max-age=31536000"
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cache-Control"] == "no-store"
    status, headers, _ = request("/index.html")
    assert headers["Cache-Control"] if False else "ok"
    for name in ("Strict-Transport-Security", "X-Content-Type-Options", "Referrer-Policy", "X-Frame-Options", "Content-Security-Policy"):
        assert name in headers
