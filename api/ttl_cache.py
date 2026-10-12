"""A short-lived memory of what a heavy screen just calculated, so the next person (or the next click) does not wait for the same calculation again.

Off unless STAXIS_RESULT_CACHE_SECONDS is set above zero (the server sets it; tests and scripts see fresh numbers every time). The key is the database it was asked of plus the arguments, never the person,
so it is only used for results that are the same for everyone who asks the same question of the same data (the public demo has its own data and never shares an answer with the real one).
A caller always gets its own copy, so changing a result cannot change what the next caller sees.

Heavy analysis screens can also be marked ``stale=True``: when STAXIS_RESULT_STALE_SECONDS is set above zero, an answer that has just expired is still handed out at once while one background thread works out
the new one, so nobody waits for a calculation that takes seconds. Live screens never use this: they are always fresh or recalculated on the spot.
"""

from __future__ import annotations

import copy
import itertools
import logging
import os
import threading
import time
import weakref
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)
MAX_ENTRIES = 256
_TOKENS: "weakref.WeakKeyDictionary[Any, int]" = weakref.WeakKeyDictionary()
_SERIAL = itertools.count(1)


def _seconds(name: str) -> float:
    try:
        return max(0.0, float(os.getenv(name, "0") or 0))
    except ValueError:
        return 0.0


def seconds_to_keep() -> float:
    return _seconds("STAXIS_RESULT_CACHE_SECONDS")


def stale_seconds() -> float:
    return _seconds("STAXIS_RESULT_STALE_SECONDS")


def _which_database(session: Any) -> int:
    """A number that is different for each database engine (the real one, the demo's, a test's), so their answers are never mixed."""
    try:
        bind = session.get_bind()
        token = _TOKENS.get(bind)
        if token is None:
            token = _TOKENS[bind] = next(_SERIAL)
        return token
    except Exception:   # no session (a script or a test) or a bind that cannot be told apart
        return 0


def ttl_cache(scale: float = 1.0, stale: bool = False, key: Callable[..., Any] | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Keep the result of ``fn(session, ...)`` for STAXIS_RESULT_CACHE_SECONDS times ``scale``. ``key`` turns the arguments into what identifies a question (default: all of them)."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        store: dict[tuple[int, str], tuple[float, Any]] = {}
        lock = threading.Lock()
        refreshing: set[tuple[int, str]] = set()

        def put(k: tuple[int, str], value: Any) -> None:
            with lock:
                if len(store) >= MAX_ENTRIES:
                    for old in sorted(store, key=lambda x: store[x][0])[: MAX_ENTRIES // 4]:
                        store.pop(old, None)
                store[k] = (time.monotonic(), copy.deepcopy(value))

        def refresh(k: tuple[int, str], session: Any, args: tuple, kwargs: dict) -> None:
            try:
                from sqlalchemy.orm import Session

                with Session(session.get_bind()) as fresh:
                    put(k, fn(fresh, *args, **kwargs))
            except Exception as exc:   # the stale answer stays until the next caller tries again
                logger.warning("background refresh of %s failed: %s", fn.__name__, type(exc).__name__)
            finally:
                with lock:
                    refreshing.discard(k)

        @wraps(fn)
        def wrapper(session: Any, *args: Any, **kwargs: Any) -> Any:
            keep = seconds_to_keep() * scale
            if keep <= 0:
                return fn(session, *args, **kwargs)
            k = (_which_database(session), repr(key(*args, **kwargs)) if key else repr((args, sorted(kwargs.items(), key=lambda item: item[0]))))
            now = time.monotonic()
            with lock:
                hit = store.get(k)
                start = False
                if hit is not None and now - hit[0] >= keep and stale and now - hit[0] < keep + stale_seconds() and k not in refreshing:
                    refreshing.add(k)
                    start = True
            if hit is not None and now - hit[0] < keep:
                return copy.deepcopy(hit[1])
            if hit is not None and stale and now - hit[0] < keep + stale_seconds():
                if start:
                    threading.Thread(target=refresh, args=(k, session, args, kwargs), daemon=True).start()
                return copy.deepcopy(hit[1])
            value = fn(session, *args, **kwargs)
            put(k, value)
            return value

        wrapper.cache_clear = lambda: store.clear()  # type: ignore[attr-defined]
        return wrapper

    return decorator
