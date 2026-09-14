import json

from api.http import get_video_intelligence, wsgi_application


class FakeSession:
    def __init__(self, payload=None):
        self.payload = payload
        self.closed = False

    def close(self):
        self.closed = True


def test_get_video_intelligence_rejects_invalid_id(monkeypatch):
    status, payload = get_video_intelligence(FakeSession(), 0)
    assert status == 400
    assert payload["error"]


def test_wsgi_returns_404_when_intelligence_is_missing(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr("api.http.latest_video_intelligence", lambda _session, _id: None)
    app = wsgi_application(lambda: session)
    captured = {}

    body = app(
        {"REQUEST_METHOD": "GET", "PATH_INFO": "/api/v1/videos/7/intelligence"},
        lambda status, headers: captured.update(status=status, headers=headers),
    )

    assert captured["status"] == "404 Not Found"
    assert json.loads(body[0]) == {"error": "intelligence not found"}
    assert session.closed is True


def test_wsgi_returns_json_for_existing_intelligence(monkeypatch):
    session = FakeSession()
    expected = {"video_id": 7, "score": 82.5}
    monkeypatch.setattr("api.http.latest_video_intelligence", lambda _session, _id: expected)
    app = wsgi_application(lambda: session)
    captured = {}

    body = app(
        {"REQUEST_METHOD": "GET", "PATH_INFO": "/api/v1/videos/7/intelligence"},
        lambda status, headers: captured.update(status=status, headers=headers),
    )

    assert captured["status"] == "200 OK"
    assert json.loads(body[0]) == expected
    assert session.closed is True


def test_wsgi_rejects_non_get_routes():
    app = wsgi_application(lambda: FakeSession())
    captured = {}

    body = app(
        {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/v1/videos/7/intelligence"},
        lambda status, headers: captured.update(status=status, headers=headers),
    )

    assert captured["status"] == "404 Not Found"
    assert json.loads(body[0]) == {"error": "not found"}
