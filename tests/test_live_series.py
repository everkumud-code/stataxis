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


# ------------------------------------------------------------------ Data of: views gained and total views
@pytest.fixture()
def engine_views():
    from collector.storage import Observation
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        alpha = _channel(s, "a", "Alpha")
        beta = _channel(s, "b", "Beta", language="English")
        a_main = _stream(s, alpha, "a-main", T0 - timedelta(days=45))
        a_event = _stream(s, alpha, "a-event", T0 + timedelta(minutes=30))
        b_main = _stream(s, beta, "b-main", T0 - timedelta(days=45))

        def put(video, minute, viewers, views):
            s.add(Observation(video_id=video.id, channel_id=video.channel_id, observed_at=T0 + timedelta(minutes=minute), view_count=views, concurrent_viewers=viewers, is_live=True, classification="LIVE", source="test"))
        for m in range(0, 120):
            put(a_main, m, 1000, 1_000_000 + 60 * m)                 # gains 60 views a minute
            if 30 <= m < 60:
                put(a_event, m, 3000, 5_000 + 100 * (m - 30))        # gains 100 a minute
            if m < 60:
                put(b_main, m, 500, 200_000 + 10 * m)                # gains 10 a minute
        s.commit()
    return engine


def measured(engine, **kw):
    with Session(engine) as s:
        return live_channel_series(s, start_at=T0, end_at=T0 + timedelta(minutes=119), **kw)


def test_views_gained_are_the_rises_of_each_streams_own_count_and_a_new_stream_adds_no_jump(engine_views):
    out = measured(engine_views, bucket_seconds=900, feed="all", measure="gained")
    a, b = by_name(out)["Alpha"], by_name(out)["Beta"]
    assert out["measure"] == "gained"
    assert a["values"][0] == 840 and a["values"][1] == 900                       # 60 a minute; the first minute has nothing before it
    assert 2200 <= a["values"][2] <= 2400                                          # the event stream (100 a minute) comes in without its 5,000 starting count being a gain
    assert a["values"][5] == 900
    assert b["values"][1] == 150 and b["values"][6] is None                        # Beta stopped; a time with no live stream is empty, not zero
    assert a["total"] == sum(v for v in a["values"] if v is not None)


def test_gained_by_feed(engine_views):
    primary = by_name(measured(engine_views, bucket_seconds=900, feed="primary", measure="gained"))["Alpha"]
    assert primary["values"][2] == 900 and primary["streams"][2] == 1
    secondary = by_name(measured(engine_views, bucket_seconds=900, feed="secondary", measure="gained"))["Alpha"]
    assert 1300 <= secondary["values"][2] <= 1500 and secondary["values"][0] is None


def test_total_views_is_the_running_total_at_the_end_of_each_bucket(engine_views):
    out = measured(engine_views, bucket_seconds=900, feed="all", measure="views")
    a = by_name(out)["Alpha"]
    assert a["values"][0] == 1_000_840.0                                           # minute 14
    assert a["values"][2] == 1_002_640.0 + 5_000 + 1_400                           # the main stream and the event, at minute 44
    assert by_name(measured(engine_views, bucket_seconds=900, feed="primary", measure="views"))["Alpha"]["values"][2] == 1_002_640.0
    assert a["total"] == a["values"][-1] and out["totals"]["latest"] is not None


def test_six_hours_of_gained_is_the_whole_days_gain_in_one_bucket(engine_views):
    out = measured(engine_views, bucket_seconds=21600, feed="all", measure="gained")
    a = by_name(out)["Alpha"]
    assert len(out["grid"]) == 1 and 7_000 + 2_900 <= a["values"][0] <= 7_300 + 3_100   # 60 a minute for two hours, and 100 a minute for half an hour
    assert out["totals"]["sum"] == a["values"][0] + by_name(out)["Beta"]["values"][0]


def test_the_default_is_still_concurrent_viewers_and_unknown_measures_are_refused(engine_views):
    assert measured(engine_views, bucket_seconds=900)["measure"] == "concurrent"
    with pytest.raises(ValueError):
        measured(engine_views, bucket_seconds=900, measure="likes")


def test_the_route_takes_the_measure(engine_views, monkeypatch):
    monkeypatch.setattr("api.live_http.authenticate", lambda header: SimpleNamespace(user_id=1))
    monkeypatch.setattr("api.live_http.policy_for_identity", lambda identity: SimpleNamespace())
    monkeypatch.setattr("api.live_http.require_capability", lambda policy, name: None)
    app = live_application(lambda: Session(engine_views))
    status, body = _call(app, f"start={T0.isoformat()}&end={(T0 + timedelta(minutes=119)).isoformat()}&bucket_seconds=900&measure=views".replace("+", "%2B"))
    assert status == "200 OK" and body["measure"] == "views" and body["channels"][0]["name"] == "Alpha"
    status, body = _call(app, f"start={T0.isoformat()}&end={(T0 + timedelta(minutes=119)).isoformat()}&bucket_seconds=900&measure=likes".replace("+", "%2B"))
    assert status == "400 Bad Request"
