from datetime import UTC, datetime, timedelta

from metrics.feeds import LiveStream, split_feeds

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def stream(video_id, viewers, hours_live):
    return LiveStream(video_id, viewers, NOW - timedelta(hours=hours_live) if hours_live is not None else None)


def test_long_running_stream_is_primary_and_the_rest_are_secondary():
    split = split_feeds([stream("main", 50_000, 72), stream("event", 12_000, 1), stream("panel", 3_000, 2)], now=NOW)
    assert (split.primary, split.secondary, split.all) == (50_000, 15_000, 65_000)
    assert split.primary_video_id == "main"
    assert split.secondary_count == 2


def test_all_feed_is_primary_plus_secondaries_even_when_secondary_is_larger():
    split = split_feeds([stream("main", 10_000, 100), stream("event", 90_000, 3)], now=NOW)
    assert split.primary == 10_000
    assert split.secondary == 90_000
    assert split.all == 100_000


def test_no_long_running_stream_means_no_primary_and_all_is_not_understated():
    split = split_feeds([stream("a", 4_000, 2), stream("b", 6_000, 5)], now=NOW)
    assert split.primary == 0
    assert split.primary_video_id is None
    assert split.secondary == 10_000
    assert split.all == 10_000


def test_unknown_start_time_is_never_primary():
    split = split_feeds([stream("unknown", 8_000, None), stream("event", 2_000, 1)], now=NOW)
    assert split.primary == 0
    assert split.all == 10_000


def test_earliest_started_eligible_stream_wins_and_ties_break_on_viewers():
    split = split_feeds([stream("newer", 90_000, 30), stream("older", 1_000, 200)], now=NOW)
    assert split.primary_video_id == "older"
    tie = split_feeds([stream("a", 1_000, 40), stream("b", 5_000, 40)], now=NOW)
    assert tie.primary_video_id == "b"


def test_threshold_is_configurable(monkeypatch):
    streams = [stream("main", 5_000, 3), stream("event", 1_000, 1)]
    assert split_feeds(streams, now=NOW).primary == 0
    monkeypatch.setenv("STAXIS_PRIMARY_MIN_LIVE_HOURS", "2")
    assert split_feeds(streams, now=NOW).primary == 5_000
    monkeypatch.setenv("STAXIS_PRIMARY_MIN_LIVE_HOURS", "not-a-number")
    assert split_feeds(streams, now=NOW).min_primary_hours == 12.0


def test_naive_datetimes_are_treated_as_utc_and_empty_input_is_zero():
    naive = LiveStream("m", 100, (NOW - timedelta(hours=48)).replace(tzinfo=None))
    assert split_feeds([naive], now=NOW.replace(tzinfo=None)).primary == 100
    empty = split_feeds([], now=NOW)
    assert (empty.primary, empty.secondary, empty.all) == (0, 0, 0)
