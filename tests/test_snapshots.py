"""Finished answers kept in the database for every web process (api/ttl_cache.py), and the warm-up loop's list of questions.
The database part needs PostgreSQL: set STAXIS_TEST_PG to a throw-away database URL to run it (it is skipped otherwise)."""
import os

import pytest

from collector import warmer


def test_the_warm_up_loop_asks_what_people_ask_most():
    quick, slow = warmer.quick_round(), warmer.slow_round()
    assert len(quick) == 14 and sum(1 for path, _ in quick if path == "/api/v1/markets/report") == 12 and ("/api/v1/lab/spikes", "hours=6") in quick      # 4 short windows x 3 languages, and the spikes and the movement
    assert ("/api/v1/markets/report", "period=1h&stream_scope=all&limit=200") in quick                           # an empty language is left out, as the screen leaves it out
    assert ("/api/v1/markets/report", "period=today&language=Hindi&stream_scope=all&limit=200") in quick
    paths = {path for path, _ in slow}
    assert {"/api/v1/insights/what-changed", "/api/v1/market/weekly", "/api/v1/market/prime-time", "/api/v1/market/authenticity", "/api/v1/market/creator-index", "/api/v1/market/briefing"} <= paths
    assert sum(1 for path, _ in slow if path == "/api/v1/market/briefing") == 15                                 # 5 roles x 3 languages
    assert len({tuple(c) for c in quick + slow}) == len(quick + slow)                                            # nothing is asked twice


@pytest.mark.skipif(not os.getenv("STAXIS_TEST_PG"), reason="needs PostgreSQL (STAXIS_TEST_PG)")
def test_a_snapshot_made_by_one_process_is_served_to_another_without_recalculating(monkeypatch):
    from sqlalchemy.orm import Session

    from api.ttl_cache import ttl_cache
    from collector.storage import Snapshot, create_database

    monkeypatch.setenv("STAXIS_RESULT_CACHE_SECONDS", "30")
    monkeypatch.setenv("STAXIS_RESULT_STALE_SECONDS", "900")
    monkeypatch.setenv("STAXIS_SNAPSHOT_SECONDS", "600")
    engine = create_database(os.environ["STAXIS_TEST_PG"])
    calls = []

    @ttl_cache(stale=True)
    def heavy(session, *, days=7):
        calls.append(days)
        return {"days": days, "nested": [1, 2, {"a": "b"}], "pair": (1, "x")}

    with Session(engine) as s:
        first = heavy(s, days=7)
        assert calls == [7] and first["nested"][2] == {"a": "b"}
        heavy.cache_clear()                                  # a different web process: nothing in its own memory
        again = heavy(s, days=7)
        assert calls == [7] and again["days"] == 7 and again["pair"] == [1, "x"]       # read from the stored snapshot (a tuple comes back as a list)
        heavy(s, days=14)
        assert calls == [7, 14]
        assert s.query(Snapshot).filter(Snapshot.key.like("%heavy:%")).count() == 2
        s.query(Snapshot).filter(Snapshot.key.like("%heavy:%")).delete(synchronize_session=False)
        s.commit()


def test_the_extra_round_prepares_the_biggest_channels_the_builder_the_planner_and_the_other_windows():
    import json as _json
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from collector.storage import Base, Channel, Observation, Video
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as s:
        chans = [Channel(youtube_channel_id=f"c{i}", name=f"Ch {i}", network="n", language="Hindi", region="India", segment="news") for i in range(12)]
        s.add_all(chans)
        s.flush()
        for rank, ch in enumerate(chans):                      # channel 11 is the biggest right now, channel 0 the smallest
            v = Video(youtube_video_id=f"v{rank}", channel_id=ch.id, title="t")
            s.add(v)
            s.flush()
            s.add(Observation(video_id=v.id, channel_id=ch.id, observed_at=now - timedelta(seconds=30), view_count=1, concurrent_viewers=1000 * (rank + 1), is_live=True, classification="LIVE", source="t"))
        s.commit()
        biggest = chans[-1].id
    ids = warmer.top_channel_ids(engine, 10)
    assert len(ids) == 10 and ids[0] == biggest and len(set(ids)) == 10
    calls = warmer.extra_round(engine)
    assert (f"/api/v1/channels/{biggest}/media-intelligence", "period=7d&stream_scope=all") in calls and (f"/api/v1/channels/{biggest}/media-intelligence", "period=today&stream_scope=all") in calls
    assert sum(1 for path, _ in calls if path.endswith("/media-intelligence")) == 10 + 4 * 2                 # every one of the ten for a week, the four biggest also for today and the last hour
    posts = [(p, b) for p, b in calls if p.startswith("POST ")]
    assert len(posts) == 12 and all(p == "POST /api/v1/market/planner" for p, _ in posts) and _json.loads(posts[0][1])["max_share_percent"] == 40
    assert sum(1 for path, q in calls if path == "/api/v1/market/report" and "feed=primary" in q) == 9 and any("start_hour=19&end_hour=22" in q for _, q in calls)
    assert ("/api/v1/lab/spikes", "hours=24") in calls and ("/api/v1/lab/movement", "minutes=120") in calls and ("/api/v1/lab/completeness", "days=7") in calls
    assert len({tuple(c) for c in calls}) == len(calls)


def test_a_form_question_is_sent_as_a_form():
    seen = {}

    def app(environ, start_response):
        seen.update(method=environ["REQUEST_METHOD"], path=environ["PATH_INFO"], body=environ["wsgi.input"].read(), length=environ["CONTENT_LENGTH"])
        start_response("200 OK", [])
        return [b"{}"]

    status, _ = warmer._call(app, "tok", "POST /api/v1/market/planner", '{"days": 7}')
    assert status == 200 and seen == {"method": "POST", "path": "/api/v1/market/planner", "body": b'{"days": 7}', "length": "11"}
