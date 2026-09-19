import pytest

from collector.youtube.quota import QuotaGuardError, RequestBudget


def test_request_budget_rejects_daily_overflow() -> None:
    budget = RequestBudget(per_minute=10, daily=2)
    budget.acquire()
    budget.acquire()
    with pytest.raises(QuotaGuardError):
        budget.acquire()


def test_request_budget_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError):
        RequestBudget(per_minute=0, daily=2)


def test_request_budget_uses_defaults_for_empty_environment(monkeypatch) -> None:
    monkeypatch.setenv("STAXIS_YOUTUBE_REQUESTS_PER_MINUTE", "  ")
    monkeypatch.setenv("STAXIS_YOUTUBE_REQUESTS_PER_DAY", "")
    budget = RequestBudget()
    assert budget.per_minute == 60
    assert budget.daily == 9000
