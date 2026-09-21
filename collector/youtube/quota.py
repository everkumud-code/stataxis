"""Process-local request budget for the YouTube collector."""

from __future__ import annotations

import os
import threading
import time
from collections import deque


class QuotaGuardError(RuntimeError):
    """Raised when the collector cannot safely issue another request."""


def _env_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        raw = str(default)
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def env_non_negative_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


class RequestBudget:
    """Bound API request rate and daily request budget for one worker."""

    def __init__(self, *, per_minute: int | None = None, daily: int | None = None) -> None:
        self.per_minute = (
            _env_positive_int("STAXIS_YOUTUBE_REQUESTS_PER_MINUTE", 60)
            if per_minute is None
            else per_minute
        )
        self.daily = (
            _env_positive_int("STAXIS_YOUTUBE_REQUESTS_PER_DAY", 9000)
            if daily is None
            else daily
        )
        if self.per_minute <= 0 or self.daily <= 0:
            raise ValueError("request budgets must be positive")
        self._lock = threading.Lock()
        self._minute: deque[float] = deque()
        self._day_started = time.time()
        self._day_count = 0

    def acquire(self, units: int = 1, *, reserve: int = 0) -> None:
        """Take ``units`` from the budget.

        ``reserve`` keeps that many requests per minute free for other callers
        (used so full collection can never starve live polling). Reserved
        callers still make progress: at least ``units`` per minute stay allowed.
        """
        if units <= 0:
            raise ValueError("units must be positive")
        if reserve < 0:
            raise ValueError("reserve must not be negative")
        while True:
            with self._lock:
                now = time.time()
                if now - self._day_started >= 86400:
                    self._day_started = now
                    self._day_count = 0
                while self._minute and now - self._minute[0] >= 60:
                    self._minute.popleft()
                if self._day_count + units > self.daily:
                    raise QuotaGuardError("collector daily request budget reached")
                if len(self._minute) + units <= max(units, self.per_minute - reserve):
                    self._day_count += units
                    self._minute.extend([now] * units)
                    return
                wait_for = max(0.05, 60 - (now - self._minute[0]))
            time.sleep(min(wait_for, 5.0))


DEFAULT_BUDGET = RequestBudget()
