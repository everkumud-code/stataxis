"""A short-lived memory of what a heavy screen just calculated, so the next person (or the next click) does not wait for the same calculation again.

Off unless STAXIS_RESULT_CACHE_SECONDS is set above zero (the server sets it; tests and scripts see fresh numbers every time). The key is the database it was asked of plus the arguments, never the person,
so it is only used for results that are the same for everyone who asks the same question of the same data (the public demo has its own data and never shares an answer with the real one).
A caller always gets its own copy, so changing a result cannot change what the next caller sees.

Heavy analysis screens can also be marked ``stale=True``: when STAXIS_RESULT_STALE_SECONDS is set above zero, an answer that has just expired is still handed out at once while one background thread works out
the new one, so nobody waits for a calculation that takes seconds. Live screens never use this: they are always fresh or recalculated on the spot.

Snapshots: with STAXIS_SNAPSHOT_SECONDS above zero (and PostgreSQL), the answers of those heavy screens are also kept in the database table stx_snapshots. The collector's warm-up loop (collector/warmer.py)
works out the popular questions every minute or few minutes and writes them there; every web process then reads the finished answer instead of working it out, so a screen opens in a few milliseconds
whichever process serves it and however long the calculation takes.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import logging
import os
import threading
import time
import weakref
from datetime import UTC, datetime
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


def snapshot_seconds() -> float:
    return _seconds("STAXIS_SNAPSHOT_SECONDS")


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


def _is_postgres(session: Any) -> bool:
    try:
        return session.get_bind().dialect.name == "postgresql"
    except Exception:
        return False


def _snapshot_key(name: str, question: str) -> str:
    return f"{name}:{hashlib.sha1(question.encode('utf-8')).hexdigest()}"


def _snapshot_read(session: Any, key: str) -> tuple[Any, float] | None:
    """(answer, age in seconds) of a stored snapshot, or None."""
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from collector.storage import Snapshot

        with Session(session.get_bind()) as reader:   # its own short look: the caller's session and its loaded objects are left alone
            row = reader.execute(select(Snapshot.payload, Snapshot.computed_at).where(Snapshot.key == key)).first()
        if row is None:
            return None
        computed = row.computed_at if row.computed_at.tzinfo else row.computed_at.replace(tzinfo=UTC)
        return json.loads(row.payload), max(0.0, (datetime.now(UTC) - computed).total_seconds())
    except Exception as exc:
        logger.warning("could not read a snapshot: %s", type(exc).__name__)
        return None


def _snapshot_write(session: Any, key: str, value: Any) -> None:
    try:
        from sqlalchemy.dialects.postgresql import insert
        from sqlalchemy.orm import Session

        from collector.storage import Snapshot

        payload = json.dumps(value, default=str)
        stmt = insert(Snapshot).values(key=key, payload=payload, computed_at=datetime.now(UTC))
        stmt = stmt.on_conflict_do_update(index_elements=[Snapshot.key], set_={"payload": stmt.excluded.payload, "computed_at": stmt.excluded.computed_at})
        with Session(session.get_bind()) as writer:   # its own short transaction: the caller's session is left alone
            writer.execute(stmt)
            writer.commit()
    except Exception as exc:
        logger.warning("could not store a snapshot: %s", type(exc).__name__)


def ttl_cache(scale: float = 1.0, stale: bool = False, key: Callable[..., Any] | None = None, snapshot: Callable[..., float] | float | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Keep the result of ``fn(session, ...)`` for STAXIS_RESULT_CACHE_SECONDS times ``scale``. ``key`` turns the arguments into what identifies a question (default: all of them).
    ``snapshot`` (seconds, or a function of the arguments that gives seconds) is how long a stored snapshot counts as fresh; it applies to ``stale=True`` functions only."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        store: dict[tuple[int, str], tuple[float, Any]] = {}
        lock = threading.Lock()
        refreshing: set[tuple[int, str]] = set()
        name = f"{fn.__module__}.{fn.__qualname__}"

        def put(k: tuple[int, str], value: Any, session: Any = None) -> None:
            with lock:
                if len(store) >= MAX_ENTRIES:
                    for old in sorted(store, key=lambda x: store[x][0])[: MAX_ENTRIES // 4]:
                        store.pop(old, None)
                store[k] = (time.monotonic(), copy.deepcopy(value))
            if stale and session is not None and snapshot_seconds() > 0 and _is_postgres(session):
                _snapshot_write(session, _snapshot_key(name, k[1]), value)

        def refresh(k: tuple[int, str], session: Any, args: tuple, kwargs: dict) -> None:
            try:
                from sqlalchemy.orm import Session

                with Session(session.get_bind()) as fresh:
                    put(k, fn(fresh, *args, **kwargs), fresh)
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
            question = repr(key(*args, **kwargs)) if key else repr((args, sorted(kwargs.items(), key=lambda item: item[0])))
            k = (_which_database(session), question)
            fresh_for = keep
            use_snapshots = stale and snapshot_seconds() > 0 and _is_postgres(session)
            if use_snapshots:
                wanted = snapshot(*args, **kwargs) if callable(snapshot) else (snapshot if snapshot is not None else snapshot_seconds())
                fresh_for = max(keep, float(wanted))
            now = time.monotonic()
            with lock:
                hit = store.get(k)
            if hit is None and use_snapshots:   # another process may have worked it out already (the warm-up loop does, every minute)
                found = _snapshot_read(session, _snapshot_key(name, k[1]))
                if found is not None:
                    value, age = found
                    hit = (now - age, value)
                    with lock:
                        store[k] = hit
            start = False
            with lock:
                if hit is not None and now - hit[0] >= fresh_for and stale and now - hit[0] < fresh_for + stale_seconds() and k not in refreshing:
                    refreshing.add(k)
                    start = True
            if hit is not None and now - hit[0] < fresh_for:
                return copy.deepcopy(hit[1])
            if hit is not None and stale and now - hit[0] < fresh_for + stale_seconds():
                if start:
                    threading.Thread(target=refresh, args=(k, session, args, kwargs), daemon=True).start()
                return copy.deepcopy(hit[1])
            value = fn(session, *args, **kwargs)
            put(k, value, session)
            return value

        wrapper.cache_clear = lambda: store.clear()  # type: ignore[attr-defined]
        return wrapper

    return decorator
