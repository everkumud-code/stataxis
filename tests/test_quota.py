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
