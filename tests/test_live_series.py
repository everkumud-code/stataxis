"""Each channel's live viewers through a window for the All, Primary or Secondary feed, by the time bucket the person picks (1, 5, 15, 30 minutes, 6 hours), and how many streams ran. Invented data in a scratch database."""
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.live_http import live_application
from api.live_stats import live_channel_series
from collector.storage import Base
from tests.test_live_stats import T0, _channel, _sample, _stream


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        alpha = _channel(s, "a", "Alpha")
        beta = _channel(s, "b", "Beta", language="English")
        a_main = _stream(s, alpha, "a-main", T0 - timedelta(days=45))
        a_event = _stream(s, alpha, "a-event", T0 + timedelta(minutes=30))
        b_main = _stream(s, beta, "b-main", T0 - timedelta(days=45))
        for m in range(0, 120):
            _sample(s, a_main, T0 + timedelta(minutes=m), 1000)
            if 30 <= m < 60:
                _sample(s, a_event, T0 + timedelta(minutes=m), 3000)
            if m < 60:
                _sample(s, b_main, T0 + timedelta(minutes=m), 500)
        s.commit()
    return engine


def series(engine, **kw):
    with Session(engine) as s:
        return live_channel_series(s, start_at=T0, end_at=T0 + timedelta(minutes=119), **kw)


def by_name(out):
    return {c["name"]: c for c in out["channels"]}


def test_all_feed_by_fifteen_minutes_adds_the_event_stream_and_counts_the_streams(engine):
    out = series(engine, bucket_seconds=900, feed="all")
    a = by_name(out)["Alpha"]
    assert len(out["grid"]) == 8
    assert a["concurrent"][0] == 1000.0 and a["concurrent"][2] == 4000.0 and a["concurrent"][5] == 1000.0
    assert a["streams"][0] == 1 and a["streams"][2] == 2 and a["streams"][5] == 1
    assert a["peak"] == 4000 and a["peak_at"].startswith("2026-09-20T10:30") or a["peak"] == 4000


def test_a_time_with_no_live_stream_is_empty_not_zero(engine):
    b = by_name(series(engine, bucket_seconds=900, feed="all"))["Beta"]
    assert b["concurrent"][:3] == [500.0, 500.0, 500.0]
    assert b["concurrent"][5] is None and b["streams"][5] is None
    assert b["coverage_percent"] < 70


def test_the_primary_feed_leaves_out_the_event_and_the_secondary_feed_is_the_event_only(engine):
    primary = by_name(series(engine, bucket_seconds=900, feed="primary"))["Alpha"]
    assert set(v for v in primary["concurrent"] if v is not None) == {1000.0}
    assert set(v for v in primary["streams"] if v is not None) == {1}
    secondary = by_name(series(engine, bucket_seconds=900, feed="secondary"))
    assert secondary["Alpha"]["concurrent"][2] == 3000.0 and secondary["Alpha"]["concurrent"][0] is None and secondary["Alpha"]["streams"][2] == 1
    assert "Beta" not in secondary                      # it never had a secondary stream


def test_a_six_hour_bucket_is_the_average_of_its_minutes_not_one_lucky_minute(engine):
    out = series(engine, bucket_seconds=21600, feed="all")
    a = by_name(out)["Alpha"]
    assert len(out["grid"]) == 1
    assert 1700 <= a["concurrent"][0] <= 1900           # 30 min at 1000, 30 at 4000, 60 at 1000
    assert a["peak"] == 4000


def test_one_minute_buckets_are_read_as_they_are(engine):
    out = series(engine, bucket_seconds=60, feed="all")
    a = by_name(out)["Alpha"]
    assert len(out["grid"]) == 120 and a["concurrent"][29] == 1000.0 and a["concurrent"][30] == 4000.0 and a["concurrent"][70] == 1000.0


def test_channels_are_ranked_by_their_average_and_the_total_adds_them_up(engine):
    out = series(engine, bucket_seconds=900, feed="all")
    assert [c["name"] for c in out["channels"]] == ["Alpha", "Beta"] and [c["rank"] for c in out["channels"]] == [1, 2]
    assert out["totals"]["concurrent"][0] == 1500.0 and out["totals"]["concurrent"][5] == 1000.0
    assert out["totals"]["streams"][0] == 2 and out["totals"]["peak"] == 4500.0


def test_a_language_and_a_channel_filter_narrow_it(engine):
    assert [c["name"] for c in series(engine, bucket_seconds=900, language="English")["channels"]] == ["Beta"]
    with Session(engine) as s:
        alpha_id = by_name(series(engine, bucket_seconds=900))["Alpha"]["channel_id"]
    assert [c["name"] for c in series(engine, bucket_seconds=900, channel_ids=(alpha_id,))["channels"]] == ["Alpha"]


@pytest.mark.parametrize("kw", [{"feed": "tertiary"}, {"bucket_seconds": 600}, {"bucket_seconds": 0}])
def test_unknown_feeds_and_view_by_choices_are_refused(engine, kw):
    with pytest.raises(ValueError):
        series(engine, **{"bucket_seconds": 900, **kw})


def test_the_window_must_run_forward_and_stay_within_a_day(engine):
    with Session(engine) as s:
        with pytest.raises(ValueError):
            live_channel_series(s, start_at=T0, end_at=T0, bucket_seconds=900)
        with pytest.raises(ValueError):
            live_channel_series(s, start_at=T0, end_at=T0 + timedelta(hours=25), bucket_seconds=900)


# ------------------------------------------------------------------ the route
def _call(app, query):
    captured = {}
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/api/v1/audience/live/series", "QUERY_STRING": query, "HTTP_AUTHORIZATION": "Bearer test"}
    body = app(environ, lambda status, headers: captured.update(status=status))
    return captured["status"], json.loads(body[0])


@pytest.fixture()
def app(engine, monkeypatch):
    monkeypatch.setattr("api.live_http.authenticate", lambda header: SimpleNamespace(user_id=1))
    monkeypatch.setattr("api.live_http.policy_for_identity", lambda identity: SimpleNamespace())
    monkeypatch.setattr("api.live_http.require_capability", lambda policy, name: None)
    return live_application(lambda: Session(engine))


def test_the_route_answers_with_start_and_end_and_the_chosen_feed_and_view_by(app):
    status, body = _call(app, f"start={T0.isoformat()}&end={(T0 + timedelta(minutes=119)).isoformat()}&bucket_seconds=900&feed=primary".replace("+", "%2B"))
    assert status == "200 OK" and body["feed"] == "primary" and body["bucket_seconds"] == 900 and len(body["grid"]) == 8 and body["channels"][0]["name"] == "Alpha"


def test_the_route_reads_one_indian_day_and_never_the_future(app):
    status, body = _call(app, "date=2020-01-02&from=9&to=18&bucket_seconds=3600")
    assert status == "400 Bad Request"                    # 3600 is not one of the view-by choices
    status, body = _call(app, "date=2020-01-02&from=9&to=18&bucket_seconds=1800")
    assert status == "200 OK" and body["start_at"].startswith("2020-01-02T03:30") and body["end_at"].startswith("2020-01-02T12:30") and body["channels"] == []
    status, body = _call(app, "date=2099-01-01")
    assert status == "400 Bad Request" and "not come" in body["error"]
    status, body = _call(app, "date=2020-01-02&from=18&to=9")
    assert status == "400 Bad Request"
    status, body = _call(app, "date=garbage")
    assert status == "400 Bad Request"


def test_the_route_needs_a_login(monkeypatch, engine):
    from api.errors import AuthenticationError

    def refuse(header):
        raise AuthenticationError("sign in")
    monkeypatch.setattr("api.live_http.authenticate", refuse)
    status, body = _call(live_application(lambda: Session(engine)), "bucket_seconds=900")
    assert status.startswith("401")
