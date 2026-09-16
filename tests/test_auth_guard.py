import json

from api.auth_guard import protect_application


def test_api_requires_authentication() -> None:
    app = protect_application(lambda _env, start: (start("200 OK", []), [b"ok"])[1])
    captured = {}
    body = app(
        {"PATH_INFO": "/api/v1/channels", "REQUEST_METHOD": "GET"},
        lambda status, headers: captured.update(status=status, headers=headers),
    )
    assert captured["status"] == "401 Unauthorized"
    assert json.loads(body[0]) == {"error": "authentication required"}


def test_non_api_health_can_remain_public() -> None:
    app = protect_application(lambda _env, start: (start("200 OK", []), [b"ok"])[1])
    captured = {}
    body = app(
        {"PATH_INFO": "/health", "REQUEST_METHOD": "GET"},
        lambda status, headers: captured.update(status=status, headers=headers),
    )
    assert captured["status"] == "200 OK"
    assert body == [b"ok"]
