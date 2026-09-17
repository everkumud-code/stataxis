from api.http import get_channel_series


class FakeSession:
    pass


def test_get_channel_series_rejects_days_outside_supported_range(monkeypatch):
    monkeypatch.setattr("api.http.channel_view_series", lambda *args, **kwargs: {"points": []})

    status, payload = get_channel_series(FakeSession(), 7, days=0)
    assert status == 400
    assert payload == {"error": "days must be between 1 and 365"}

    status, payload = get_channel_series(FakeSession(), 7, days=366)
    assert status == 400
    assert payload == {"error": "days must be between 1 and 365"}
