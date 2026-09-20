"""Process-local sliding-window rate limiting for security-sensitive endpoints."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


class SlidingWindowRateLimiter:
    """Thread-safe, process-local sliding-window limiter."""

    def __init__(self):
        self._events = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, limit: int, window_seconds: int, now: float | None = None) -> int:
        current = time.monotonic() if now is None else now
        cutoff = current - window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return max(1, int(events[0] + window_seconds - current))
            events.append(current)
            return 0

    def reset(self):
        with self._lock:
            self._events.clear()


limiter = SlidingWindowRateLimiter()


def client_ip(environ: dict[str, object]) -> str:
    forwarded = str(environ.get("HTTP_X_FORWARDED_FOR", "")).strip()
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return str(environ.get("REMOTE_ADDR", "")).strip() or "unknown"
