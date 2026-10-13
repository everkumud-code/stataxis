"""Finished answers kept in the database for every web process (api/ttl_cache.py), and the warm-up loop's list of questions.
The database part needs PostgreSQL: set STAXIS_TEST_PG to a throw-away database URL to run it (it is skipped otherwise)."""
import os

import pytest

from collector import warmer


def test_the_warm_up_loop_asks_what_people_ask_most():
    quick, slow = warmer.quick_round(), warmer.slow_round()
    assert len(quick) == 12 and all(path == "/api/v1/markets/report" for path, _ in quick)                      # 4 short windows x 3 languages
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
