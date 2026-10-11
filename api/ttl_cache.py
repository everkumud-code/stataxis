"""A short-lived memory of what a heavy screen just calculated, so the next person (or the next click) does not wait for the same calculation again.

Off unless STAXIS_RESULT_CACHE_SECONDS is set above zero (the server sets it; tests and scripts see fresh numbers every time). The key is the arguments, never the person, so it is only used
for results that are the same for everyone who asks the same question. A caller always gets its own copy, so changing a result cannot change what the next caller sees.
"""

from __future__ import annotations

import copy
import os
import threading
import time
from functools import wraps
from typing import Any, Callable

MAX_ENTRIES = 256


def seconds_to_keep() -> float:
    try:
        return max(0.0, float(os.getenv("STAXIS_RESULT_CACHE_SECONDS", "0") or 0))
    except ValueError:
        return 0.0


def ttl_cache(scale: float = 1.0) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Keep the result of ``fn(session, ...)`` for STAXIS_RESULT_CACHE_SECONDS times ``scale``."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        store: dict[str, tuple[float, Any]] = {}
        lock = threading.Lock()

        @wraps(fn)
        def wrapper(session: Any, *args: Any, **kwargs: Any) -> Any:
            keep = seconds_to_keep() * scale
            if keep <= 0:
                return fn(session, *args, **kwargs)
            key = repr((args, sorted(kwargs.items(), key=lambda item: item[0])))
            now = time.monotonic()
            with lock:
                hit = store.get(key)
            if hit is not None and now - hit[0] < keep:
                return copy.deepcopy(hit[1])
            value = fn(session, *args, **kwargs)
            with lock:
                if len(store) >= MAX_ENTRIES:
                    for old in sorted(store, key=lambda k: store[k][0])[: MAX_ENTRIES // 4]:
                        store.pop(old, None)
                store[key] = (now, copy.deepcopy(value))
            return value

        wrapper.cache_clear = lambda: store.clear()  # type: ignore[attr-defined]
        return wrapper

    return decorator
