"""The short memory of heavy screens: off by default, shared by identical questions, never shared by different ones, and every caller gets its own copy."""
import time

import pytest

from api.ttl_cache import ttl_cache


def make():
    calls = []

    @ttl_cache()
    def heavy(session, *, days=7, ids=None):
        calls.append((days, ids))
        return {"days": days, "ids": ids, "list": [1, 2, 3]}

    return heavy, calls


def test_it_is_off_until_the_server_turns_it_on(monkeypatch):
    monkeypatch.delenv("STAXIS_RESULT_CACHE_SECONDS", raising=False)
    heavy, calls = make()
    heavy(None, days=7)
    heavy(None, days=7)
    assert len(calls) == 2


def test_the_same_question_is_answered_from_memory_and_a_different_one_is_not(monkeypatch):
    monkeypatch.setenv("STAXIS_RESULT_CACHE_SECONDS", "30")
    heavy, calls = make()
    first = heavy(None, days=7, ids=[1, 2])
    again = heavy(None, days=7, ids=[1, 2])
    assert first == again and len(calls) == 1
    heavy(None, days=14, ids=[1, 2])
    heavy(None, days=7, ids=[1, 3])
    assert len(calls) == 3


def test_a_caller_cannot_change_what_the_next_caller_gets(monkeypatch):
    monkeypatch.setenv("STAXIS_RESULT_CACHE_SECONDS", "30")
    heavy, _ = make()
    a = heavy(None, days=7)
    a["list"].append("tampered")
    a["days"] = 999
    b = heavy(None, days=7)
    assert b["list"] == [1, 2, 3] and b["days"] == 7


def test_the_memory_expires_and_the_scale_shortens_it(monkeypatch):
    monkeypatch.setenv("STAXIS_RESULT_CACHE_SECONDS", "0.2")
    heavy, calls = make()
    heavy(None)
    time.sleep(0.25)
    heavy(None)
    assert len(calls) == 2

    @ttl_cache(scale=0.1)
    def live(session):
        calls.append("live")
        return {}

    monkeypatch.setenv("STAXIS_RESULT_CACHE_SECONDS", "1")
    live(None)
    time.sleep(0.15)
    live(None)
    assert calls.count("live") == 2


def test_a_bad_setting_means_off(monkeypatch):
    monkeypatch.setenv("STAXIS_RESULT_CACHE_SECONDS", "soon")
    heavy, calls = make()
    heavy(None)
    heavy(None)
    assert len(calls) == 2


def test_two_databases_never_share_an_answer(monkeypatch):
    """The public demo runs the same code on its own data: an answer worked out for the real data must not be handed to the demo, or the other way round."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    monkeypatch.setenv("STAXIS_RESULT_CACHE_SECONDS", "30")
    calls = []

    @ttl_cache()
    def heavy(session, *, days=7):
        calls.append(id(session.get_bind()))
        return {"engine": id(session.get_bind())}

    a, b = create_engine("sqlite://"), create_engine("sqlite://")
    with Session(a) as sa, Session(b) as sb, Session(a) as sa2:
        first, other, again = heavy(sa), heavy(sb), heavy(sa2)
    assert first != other and first == again and len(calls) == 2


def test_a_just_expired_answer_is_handed_out_at_once_while_it_is_refreshed_in_the_background(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    monkeypatch.setenv("STAXIS_RESULT_CACHE_SECONDS", "0.1")
    monkeypatch.setenv("STAXIS_RESULT_STALE_SECONDS", "30")
    counter = {"n": 0}

    @ttl_cache(stale=True)
    def slow(session):
        counter["n"] += 1
        if counter["n"] > 1:
            time.sleep(0.3)
        return {"n": counter["n"]}

    @ttl_cache()
    def plain(session):
        counter["n"] += 100
        time.sleep(0.2)
        return {"n": counter["n"]}

    engine = create_engine("sqlite://")
    with Session(engine) as s:
        assert slow(s) == {"n": 1}
        time.sleep(0.15)
        t = time.time()
        assert slow(s) == {"n": 1} and time.time() - t < 0.2     # the old answer, with no wait
        assert slow(s) == {"n": 1}                                 # a second caller does not start a second refresh
        deadline = time.time() + 3
        while time.time() < deadline and slow(s) == {"n": 1}:
            time.sleep(0.05)
        assert slow(s) == {"n": 2} and counter["n"] == 2          # exactly one refresh ran
        plain(s)
        time.sleep(0.15)
        t = time.time()
        plain(s)
        assert time.time() - t >= 0.2                              # an answer not marked stale=True is recalculated on the spot
