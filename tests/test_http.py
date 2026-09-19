import json
from datetime import UTC, datetime

from api.http import get_channel_report, get_collection_health, get_video_intelligence, wsgi_application


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
    assert captured["status"] == "405 Method Not Allowed"
    assert json.loads(body[0]) == {"error": "method not allowed"}


def test_wsgi_passes_as_of_to_channel_comparison(monkeypatch):
    session = FakeSession()
    captured_args = {}
    expected = {"channel_id": 7, "as_of": "2026-09-01T00:00:00+00:00"}
    def fake_comparison(_session, channel_id, *, as_of=None):
        captured_args.update(channel_id=channel_id, as_of=as_of)
        return expected
    monkeypatch.setattr("api.http.channel_intelligence_comparison", fake_comparison)
    app = wsgi_application(lambda: session)
    captured = {}
    body = app(
        {"REQUEST_METHOD": "GET", "PATH_INFO": "/api/v1/channels/7/comparison", "QUERY_STRING": "as_of=2026-09-01T00:00:00+00:00"},
        lambda status, headers: captured.update(status=status, headers=headers),
    )
    assert captured["status"] == "200 OK"
    assert json.loads(body[0]) == expected
    assert captured_args["channel_id"] == 7
    assert captured_args["as_of"].isoformat() == "2026-09-01T00:00:00+00:00"
    assert session.closed is True


def test_wsgi_rejects_invalid_as_of(monkeypatch):
    app = wsgi_application(lambda: FakeSession())
    captured = {}
    body = app(
        {"REQUEST_METHOD": "GET", "PATH_INFO": "/api/v1/channels/compare", "QUERY_STRING": "ids=1,2&as_of=not-a-date"},
        lambda status, headers: captured.update(status=status, headers=headers),
    )
    assert captured["status"] == "400 Bad Request"
    assert json.loads(body[0]) == {"error": "as_of must be an ISO datetime"}


def test_get_channel_report_validates_ranges(monkeypatch):
    status, payload = get_channel_report(FakeSession(), 7, series_days=0)
    assert status == 400
    assert payload == {"error": "series_days must be between 1 and 365"}
    status, payload = get_channel_report(FakeSession(), 7, signal_hours=169)
    assert status == 400
    assert payload == {"error": "signal_hours must be between 1 and 168"}


def test_wsgi_channel_report_composes_real_sections(monkeypatch):
    session = FakeSession()
    calls = {}
    expected_overview = {"channel_id": 7, "name": "Aaj Tak", "youtube_channel_id": None}
    expected_comparison = {"as_of": "2026-09-01T00:00:00+00:00", "comparisons": {}}
    expected_series = {"as_of": "2026-09-01T00:00:00+00:00", "points": [{"value": 10}]}
    expected_signals = {"signals": [{"name": "momentum", "direction": "up"}]}
    monkeypatch.setattr("api.report.channel_intelligence_overview", lambda _session, _id: expected_overview)
    monkeypatch.setattr("api.report.channel_intelligence_comparison", lambda _session, _id, *, as_of=None: calls.update(as_of=as_of) or expected_comparison)
    monkeypatch.setattr("api.report.channel_view_series", lambda _session, _id, *, as_of=None, days=30: calls.update(series_days=days, series_as_of=as_of) or expected_series)
    monkeypatch.setattr("api.report.channel_signals", lambda _session, _id, *, window_hours=24: calls.update(signal_hours=window_hours) or expected_signals)
    app = wsgi_application(lambda: session)
    captured = {}
    body = app(
        {"REQUEST_METHOD": "GET", "PATH_INFO": "/api/v1/channels/7/report", "QUERY_STRING": "as_of=2026-09-01T00:00:00+00:00&series_days=90&signal_hours=48"},
        lambda status, headers: captured.update(status=status, headers=headers),
    )
    payload = json.loads(body[0])
    assert captured["status"] == "200 OK"
    assert payload["report_version"] == "v1"
    assert payload["channel"] == expected_overview
    assert payload["overview"] == expected_overview
    assert payload["comparison"] == expected_comparison
    assert payload["view_series"] == expected_series
    assert payload["signals"] == expected_signals
    assert calls["as_of"] == datetime(2026, 9, 1, tzinfo=UTC)
    assert calls["series_as_of"] == datetime(2026, 9, 1, tzinfo=UTC)
    assert calls["series_days"] == 90
    assert calls["signal_hours"] == 48
    assert session.closed is True


def test_get_collection_health_delegates_validation(monkeypatch):
    monkeypatch.setattr("api.http.collection_health", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("stale_after_minutes must be positive")))
    status, payload = get_collection_health(FakeSession(), stale_after_minutes=0)
    assert status == 400
    assert payload == {"error": "stale_after_minutes must be positive"}


def test_wsgi_collection_health_is_read_only_and_timestamped(monkeypatch):
    session = FakeSession()
    calls = {}
    expected = {"status": "success", "fresh": True, "latest_run": {"id": 9}}
    def fake_health(_session, *, as_of=None, stale_after_minutes=360):
        calls.update(as_of=as_of, stale_after_minutes=stale_after_minutes)
        return expected
    monkeypatch.setattr("api.http.collection_health", fake_health)
    app = wsgi_application(lambda: session)
    captured = {}
    body = app(
        {"REQUEST_METHOD": "GET", "PATH_INFO": "/api/v1/operations/collection", "QUERY_STRING": "as_of=2026-09-15T00:00:00+00:00&stale_after_minutes=90"},
        lambda status, headers: captured.update(status=status, headers=headers),
    )
    assert captured["status"] == "200 OK"
    assert json.loads(body[0]) == expected
    assert calls["as_of"] == datetime(2026, 9, 15, tzinfo=UTC)
    assert calls["stale_after_minutes"] == 90
    assert session.closed is True
