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
