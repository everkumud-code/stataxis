import pytest

from collector.youtube.quota import QuotaGuardError, RequestBudget, env_non_negative_int


def test_reserve_leaves_room_for_priority_callers_without_starving_the_reserved_one():
    budget = RequestBudget(per_minute=10, daily=1000)
    for _ in range(4):  # a reserved caller may use 10 - 6 = 4 per minute
        budget.acquire(reserve=6)
    for _ in range(6):  # a normal caller still gets the other 6 immediately
        budget.acquire()
    assert len(budget._minute) == 10


def test_reserve_larger_than_budget_still_lets_one_request_through():
    budget = RequestBudget(per_minute=5, daily=1000)
    budget.acquire(reserve=100)
    assert len(budget._minute) == 1


def test_daily_budget_is_shared_regardless_of_reserve():
    budget = RequestBudget(per_minute=100, daily=3)
    budget.acquire(reserve=10)
    budget.acquire()
    budget.acquire(reserve=10)
    with pytest.raises(QuotaGuardError):
        budget.acquire()


def test_negative_reserve_is_rejected():
    with pytest.raises(ValueError):
        RequestBudget(per_minute=5, daily=5).acquire(reserve=-1)


def test_env_non_negative_int(monkeypatch):
    monkeypatch.delenv("X_RESERVE", raising=False)
    assert env_non_negative_int("X_RESERVE", 0) == 0
    monkeypatch.setenv("X_RESERVE", "25")
    assert env_non_negative_int("X_RESERVE", 0) == 25
    for bad in ("-1", "abc"):
        monkeypatch.setenv("X_RESERVE", bad)
        with pytest.raises(ValueError):
            env_non_negative_int("X_RESERVE", 0)
