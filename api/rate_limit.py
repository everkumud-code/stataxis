"""Process-local sliding-window rate limiting for security-sensitive endpoints."""

from __future__ import annotations

import os
import time
from collections import deque
from threading import Lock

MAX_TRACKED_KEYS = 10_000


class SlidingWindowRateLimiter:
    """Thread-safe, process-local sliding-window limiter with bounded memory."""

    def __init__(self, max_keys: int = MAX_TRACKED_KEYS):
        self._events: dict[str, tuple[int, deque[float]]] = {}
        self._max_keys = max_keys
        self._lock = Lock()

    def check(self, key: str, limit: int, window_seconds: int, now: float | None = None) -> int:
        current = time.monotonic() if now is None else now
        cutoff = current - window_seconds
        with self._lock:
            entry = self._events.get(key)
            if entry is None:
                if len(self._events) >= self._max_keys:
                    self._evict(current)
                events: deque[float] = deque()
                self._events[key] = (window_seconds, events)
            else:
                events = entry[1]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return max(1, int(events[0] + window_seconds - current))
            events.append(current)
            return 0

    def _evict(self, current: float) -> None:
        """Drop expired keys; if still full, drop the oldest-tracked keys (caller holds lock)."""
        expired = [
            key for key, (window, events) in self._events.items()
            if not events or events[-1] <= current - window
        ]
        for key in expired:
            del self._events[key]
        overflow = len(self._events) - int(self._max_keys * 0.9)
        for key in list(self._events)[:max(0, overflow)]:
            del self._events[key]

    def reset(self):
        with self._lock:
            self._events.clear()


limiter = SlidingWindowRateLimiter()


def _trusted_proxy_hops() -> int:
    raw = os.getenv("STAXIS_TRUSTED_PROXIES", "1").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 1


def client_ip(environ: dict[str, object]) -> str:
    """Return the client address without trusting client-supplied X-Forwarded-For entries.

    Each trusted proxy appends the address it received the request from, so the
    real client is the Nth entry from the right (N = STAXIS_TRUSTED_PROXIES, default 1,
    matching a single platform proxy such as Render). The leftmost entries can be
    forged by the client and must not be used as a rate-limit identity. Set
    STAXIS_TRUSTED_PROXIES=0 when the app is exposed directly with no proxy.
    """
    hops = _trusted_proxy_hops()
    forwarded = [part.strip() for part in str(environ.get("HTTP_X_FORWARDED_FOR", "")).split(",") if part.strip()]
    if hops and forwarded:
        return forwarded[-hops] if len(forwarded) >= hops else forwarded[0]
    return str(environ.get("REMOTE_ADDR", "")).strip() or "unknown"
