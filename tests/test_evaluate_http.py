import io
import json

from api.errors import AuthenticationError, AuthorizationError
from api.evaluate_http import evaluate_application


def _request(app, authorization):
    payload = json.dumps({"url": "https://youtu.be/dQw4w9WgXcQ", "display_name": "Test"}).encode()
    captured = {}
    body = app(
        {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/api/v1/evaluate/youtube",
            "CONTENT_LENGTH": str(len(payload)),
            "wsgi.input": io.BytesIO(payload),
            "HTTP_AUTHORIZATION": authorization,
        },
        lambda status, headers: captured.update(status=status, headers=headers),
    )
    return captured["status"], json.loads(body[0])


def test_evaluate_returns_401_for_authentication_failure(monkeypatch):
    monkeypatch.setattr(
        "api.evaluate_http.authenticate",
        lambda _authorization: (_ for _ in ()).throw(AuthenticationError("authentication required")),
    )
    app = evaluate_application(lambda: None)

    status, body = _request(app, None)

    assert status == "401 Unauthorized"
    assert body == {"error": "authentication required"}


def test_evaluate_returns_403_for_authorization_failure(monkeypatch):
    monkeypatch.setattr("api.evaluate_http.authenticate", lambda _authorization: object())
    monkeypatch.setattr(
        "api.evaluate_http.evaluate_youtube_url",
        lambda *args: (_ for _ in ()).throw(AuthorizationError("premium access required")),
    )
    app = evaluate_application(lambda: None)

    status, body = _request(app, "Bearer test")

    assert status == "403 Forbidden"
    assert body == {"error": "premium access required"}
