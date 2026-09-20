import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.live_http import live_application
from api.live_stats import live_snapshot, live_window_stats
from collector.storage import Base, Channel, Observation, Video

T0 = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)


def at(minutes, seconds=0):
    return T0 + timedelta(minutes=minutes, seconds=seconds)


def _session():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def _channel(session, key, name, language="Hindi", segment="news"):
    channel = Channel(youtube_channel_id=key, name=name, network="n", language=language, region="India", segment=segment)
    session.add(channel)
    session.flush()
    return channel


def _stream(session, channel, key, started_at):
    video = Video(youtube_video_id=key, channel_id=channel.id, title=key, live_started_at=started_at)
    session.add(video)
    session.flush()
    return video


def _sample(session, video, when, viewers):
    session.add(Observation(video_id=video.id, channel_id=video.channel_id, observed_at=when,
                            view_count=1, concurrent_viewers=viewers, is_live=True, classification="LIVE", source="test"))


def _seed_primary_and_event(session):
    channel = _channel(session, "c1", "Alpha")
    main = _stream(session, channel, "main", T0 - timedelta(days=45))
    event = _stream(session, channel, "event", T0 - timedelta(hours=1))
    for minute in range(0, 6):
        for second in (0, 30):
            viewers = 2000 if (minute, second) == (3, 0) else 1000
            _sample(session, main, at(minute, second), viewers)
    for when, viewers in ((at(2, 10), 300), (at(3, 10), 500), (at(4, 10), 400)):
        _sample(session, event, when, viewers)
    session.commit()
    return channel


def test_window_average_and_peak_are_time_aligned_across_streams():
    session = _session()
    _seed_primary_and_event(session)
    payload = live_window_stats(session, start_at=at(0), end_at=at(5))
    row = payload["channels"][0]
    # All by minute: 1000, 1000, 1000, 2300, 1500, 1400
    assert row["feeds"]["all"] == {"average": 1366.7, "peak": 2300}
    assert row["feeds"]["primary"] == {"average": 1166.7, "peak": 2000}
    assert row["feeds"]["secondary"] == {"average": 200.0, "peak": 500}
    assert row["peak_at"] == at(3).isoformat()
    assert row["streams_seen"] == 2
    assert row["coverage_percent"] == 100.0
    assert row["market_label"] == "Hindi News"
    assert payload["interpolation"] is False and "carried forward" in payload["method"]
    # The combined peak (2300) exceeds the largest single-stream sample (2000): the old approach missed this.
    assert row["feeds"]["all"]["peak"] > 2000


def test_snapshot_at_a_chosen_minute_splits_primary_secondary_all():
    session = _session()
    _seed_primary_and_event(session)
    payload = live_snapshot(session, at=at(3))
    assert payload["channels"][0]["feeds"] == {"primary": 2000, "secondary": 300, "all": 2300}
    assert payload["markets"][0]["all"] == 2300 and payload["markets"][0]["channels"] == 1


def test_ended_stream_stops_counting_after_the_freshness_window():
    session = _session()
    channel = _channel(session, "c1", "Alpha")
    main = _stream(session, channel, "main", T0 - timedelta(days=45))
    event = _stream(session, channel, "event", T0 - timedelta(hours=1))
    for minute in range(0, 7):
        _sample(session, main, at(minute), 1000)
    _sample(session, event, at(0, 10), 700)
    session.commit()
    early = live_snapshot(session, at=at(1))["channels"][0]["feeds"]
    late = live_snapshot(session, at=at(5))["channels"][0]["feeds"]
    assert early["secondary"] == 700
    assert late["secondary"] == 0 and late["all"] == 1000


def test_no_live_data_is_not_zero_filled():
    session = _session()
    channel = _channel(session, "c1", "Alpha")
    main = _stream(session, channel, "main", T0 - timedelta(days=45))
    _sample(session, main, at(0), 1000)
    _sample(session, main, at(1), 1000)
    session.commit()
    row = live_window_stats(session, start_at=at(0), end_at=at(9))["channels"][0]
    assert row["feeds"]["all"]["average"] == 1000.0  # not diluted by the minutes it was not live
    assert row["coverage_percent"] < 100


def test_market_share_headline_and_business_segment_market():
    session = _session()
    for key, name, language, segment, viewers in (
        ("a", "Alpha", "Hindi", "news", 3000), ("b", "Bravo", "Hindi", "news", 1000),
        ("c", "Charlie", "English", "business", 500), ("d", "Delta", "Hindi", "business", 500),
    ):
        channel = _channel(session, key, name, language, segment)
        stream = _stream(session, channel, key + "-live", T0 - timedelta(days=60))
        for minute in range(0, 3):
            _sample(session, stream, at(minute), viewers)
    session.commit()
    payload = live_window_stats(session, start_at=at(0), end_at=at(2))
    labels = {market["label"]: market for market in payload["markets"]}
    assert set(labels) == {"Hindi News", "Business News"}
    assert labels["Business News"]["channel_count"] == 2  # English + Hindi business channels share one market
    shares = {row["name"]: row["share_percent"] for row in payload["channels"]}
    assert shares["Alpha"] == 75.0 and shares["Bravo"] == 25.0 and shares["Charlie"] == 50.0
    assert "Alpha led with 75% share followed by Bravo" in labels["Hindi News"]["headline"]
    business_only = live_window_stats(session, start_at=at(0), end_at=at(2), segment="business")
    assert {row["name"] for row in business_only["channels"]} == {"Charlie", "Delta"}
    english_only = live_window_stats(session, start_at=at(0), end_at=at(2), language="English")
    assert {row["name"] for row in english_only["channels"]} == {"Charlie"}


@pytest.mark.parametrize("kwargs,message", [
    ({"start_at": at(5), "end_at": at(0)}, "after start_at"),
    ({"start_at": at(0), "end_at": at(0) + timedelta(hours=25)}, "24 hours"),
    ({"start_at": at(0), "end_at": at(5), "bucket_seconds": 10}, "at least 30"),
    ({"start_at": at(0), "end_at": at(5), "segment": "nonsense"}, "segment must be one of"),
])
def test_invalid_requests_are_rejected(kwargs, message):
    with pytest.raises(ValueError, match=message):
        live_window_stats(_session(), **kwargs)


def test_stats_and_snapshot_endpoints_require_authentication():
    app = live_application(lambda: _session())
    for path in ("/api/v1/audience/live/stats", "/api/v1/audience/live/snapshot", "/api/v1/audience/live/stats/export"):
        captured = {}
        environ = {"PATH_INFO": path, "REQUEST_METHOD": "GET", "QUERY_STRING": "", "wsgi.input": io.BytesIO(b"")}
        body = app(environ, lambda status, headers: captured.update(status=status))
        assert captured["status"].startswith("401"), path
        assert "error" in json.loads(body[0])
