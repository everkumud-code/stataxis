"""A channel that is switched off is in no report, no download and no post, and the stored answers forget it at once; a channel with no data is left out of a post."""
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api import forecasts
from api.dashboard_data import market_topic_distribution
from api.export import ObservationExportFilters, filtered_observations
from api.live_stats import live_window_stats
from api.market_tools import prime_time
from api.media_intelligence import market_report
from api.report_builder import build_report
from api.ttl_cache import ttl_cache
from collector.storage import Base, Channel, Observation, Prediction, Video

NOW = datetime(2026, 10, 12, 18, 0, tzinfo=UTC)          # 23:30 in India
IST_SHIFT = timedelta(hours=5, minutes=30)


def make():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return Session(engine), engine


def seed(s):
    on = Channel(youtube_channel_id="on", name="Stays On", network="n", language="Hindi", region="India", segment="news")
    off = Channel(youtube_channel_id="off", name="Switched Off", network="n", language="Hindi", region="India", segment="news")
    s.add_all([on, off])
    s.flush()
    day = date(2026, 10, 11)
    start = datetime(day.year, day.month, day.day, 19, tzinfo=UTC) - IST_SHIFT
    for ch, level in ((on, 5000), (off, 9000)):
        v = Video(youtube_video_id="v-" + ch.youtube_channel_id, channel_id=ch.id, title="a stream of " + ch.name, topic="Politics", live_started_at=start - timedelta(days=60), published_at=start.isoformat())
        s.add(v)
        s.flush()
        for m in range(180):
            s.add(Observation(video_id=v.id, channel_id=ch.id, observed_at=start + timedelta(minutes=m), view_count=1000 + m, concurrent_viewers=level, is_live=True, classification="LIVE", source="t"))
    s.commit()
    return on, off, start


def test_a_switched_off_channel_is_in_no_report_no_download_and_no_topic_list():
    s, _ = make()
    on, off, start = seed(s)
    off.active = False
    s.commit()
    names = lambda rows: {r["name"] if "name" in r else r["channel"] for r in rows}
    assert names(market_report(s, as_of=NOW, period="7d")["channels"]) == {"Stays On"}
    assert {r["name"] for r in live_window_stats(s, start_at=start, end_at=start + timedelta(hours=3))["channels"]} == {"Stays On"}
    assert {r["name"] for r in build_report(s, start_date="2026-10-11", end_date="2026-10-11", start_hour=19, end_hour=22, scope="live", now=NOW)["rows"]} == {"Stays On"}
    slot = prime_time(s, start_date="2026-10-11", end_date="2026-10-11", slots=[(19, 20)], now=NOW)["slots"][0]
    assert {r["name"] for r in slot["channels"]} == {"Stays On"}
    assert {channel.name for _o, _v, channel in filtered_observations(s, ObservationExportFilters())} == {"Stays On"}                  # the Excel download
    assert {c["name"] for c in market_topic_distribution(s, period="30d", as_of=NOW)["channels"]} == {"Stays On"}
    off.active = True
    s.commit()                                                                                                                         # switched on again: it is back, with its history
    assert names(market_report(s, as_of=NOW, period="7d")["channels"]) == {"Stays On", "Switched Off"}


def test_forecasts_do_not_list_a_channel_that_was_switched_off_after_its_forecast():
    s, _ = make()
    on, off, _start = seed(s)
    for ch in (on, off):
        s.add(Prediction(target_date="2026-10-12", slot="19:00-22:00", channel_id=ch.id, predicted=5000.0, days_used=3))
    off.active = False
    s.commit()
    listed = forecasts.forecast_overview(s, now=NOW)["upcoming"]
    assert [row["channel"] for row in listed] == ["Stays On"]


def test_the_stored_answers_forget_a_channel_the_moment_the_list_changes(monkeypatch):
    monkeypatch.setenv("STAXIS_RESULT_CACHE_SECONDS", "300")
    s, _ = make()
    on, off, _start = seed(s)
    calls = []

    @ttl_cache(stale=True)
    def who(session):
        calls.append(1)
        return [c.name for c in session.query(Channel).filter(Channel.active.is_(True)).order_by(Channel.name)]

    assert who(s) == ["Stays On", "Switched Off"] and who(s) == ["Stays On", "Switched Off"] and len(calls) == 1                     # kept
    on.avatar_url = "https://example.com/a.png"                                                                                       # a change that no report shows
    s.commit()
    from api import ttl_cache as cache_module
    cache_module._EPOCH_MEMO.clear()
    who(s)
    assert len(calls) == 1
    off.active = False                                                                                                                # the owner switches a channel off
    s.commit()
    cache_module._EPOCH_MEMO.clear()                                                                                                  # (another process would see it within three seconds)
    assert who(s) == ["Stays On"] and len(calls) == 2
    s.add(Channel(youtube_channel_id="new", name="Newly Added", network="n", language="Hindi", region="India", segment="news"))
    s.commit()
    cache_module._EPOCH_MEMO.clear()
    assert who(s) == ["Newly Added", "Stays On"] and len(calls) == 3                                                                  # a new channel too


def test_a_channel_with_no_data_is_left_out_of_a_post():
    bar = (Path(__file__).resolve().parent.parent / "dashboard" / "reportbar.js").read_text(encoding="utf-8")
    assert "r.value != null && r.value > 0" in bar and "if (kept.length) return" in bar                    # only channels with figures are drawn as bars
    assert "row.slice(1).some(c => /\\d/.test(c))" in bar                                                    # and rows with no figures are not written out as lines
