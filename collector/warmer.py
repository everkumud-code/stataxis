"""Keeps the heavy screens' answers ready: asks the questions people ask most, over and over, and stores the finished answers (api/ttl_cache.py, table stx_snapshots).

It asks through the real web application (an in-process call, with a token for the administrator account), so what it stores is exactly what a person's screen would have asked for.
Two rounds: the short windows (last hour, 3 hours, 6 hours, today) every minute, everything else every few minutes. It runs in the collector's container, which has the lower CPU share, so a
busy moment on the web screens always comes first. Off unless STAXIS_SNAPSHOT_SECONDS is above zero.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta, timezone
from threading import Event
from typing import Any

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
LANGUAGES = ("", "Hindi", "English")
PERSONAS = ("media", "buyer", "politician", "influencer", "audience")


def _q(**params: Any) -> str:
    return "&".join(f"{k}={v}" for k, v in params.items() if v not in ("", None))


def quick_round() -> list[tuple[str, str]]:
    """The windows that move every minute."""
    calls = [("/api/v1/markets/report", _q(period=period, language=lang, stream_scope="all", limit=200)) for period in ("1h", "3h", "6h", "today") for lang in LANGUAGES]
    return calls + [("/api/v1/lab/spikes", "hours=6"), ("/api/v1/lab/movement", "minutes=30")]


def slow_round() -> list[tuple[str, str]]:
    """The analysis screens, with the answers each is first opened on."""
    today = datetime.now(IST).date()
    yesterday = today - timedelta(days=1)
    week = _q(**{"from": (yesterday - timedelta(days=6)).isoformat(), "to": yesterday.isoformat()})
    calls: list[tuple[str, str]] = [("/api/v1/markets/report", _q(period="7d", language=lang, stream_scope="all", limit=200)) for lang in LANGUAGES]
    calls += [("/api/v1/markets/report", _q(period=p, stream_scope="all", limit=200)) for p in ("3w", "month")]
    calls += [("/api/v1/operations/readiness", ""), ("/api/v1/markets/topics", ""), ("/api/v1/lab/completeness", "days=3")]
    calls += [("/api/v1/insights/what-changed", f"hours={h}") for h in (24, 72, 168)]
    calls += [("/api/v1/market/weekly", week), ("/api/v1/market/prime-time", week), ("/api/v1/market/authenticity", "days=7"), ("/api/v1/market/creator-index", "days=30")]
    calls += [("/api/v1/market/briefing", _q(persona=persona, days=7, language=lang)) for persona in PERSONAS for lang in LANGUAGES]
    return calls


def _call(app: Any, token: str, path: str, query: str) -> tuple[int, float]:
    out: dict[str, Any] = {}
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": query, "wsgi.input": io.BytesIO(b""), "CONTENT_LENGTH": "0", "REMOTE_ADDR": "127.0.0.1", "HTTP_AUTHORIZATION": "Bearer " + token}
    started = time.monotonic()
    b"".join(app(environ, lambda status, headers, *a: out.update(status=status)))
    return int(str(out.get("status", "500"))[:3]), time.monotonic() - started


def _token(engine: Any) -> str | None:
    from sqlalchemy.orm import Session

    from api.auth import AuthIdentity, issue_token
    from collector.storage import User

    with Session(engine) as session:
        admin = session.query(User).filter(User.is_admin.is_(True), User.active.is_(True)).order_by(User.id).first()
        if admin is None:
            return None
        return issue_token(AuthIdentity(admin.id, admin.email, admin.plan, True), ttl_seconds=3600)


def warm_forever(engine: Any, stop: Event, *, quick_seconds: int = 100, slow_seconds: int = 420) -> None:
    from api.ttl_cache import FORCE, snapshot_seconds

    if snapshot_seconds() <= 0:
        logger.info("warm-up loop off (STAXIS_SNAPSHOT_SECONDS is not set)")
        return
    import web   # the same application the web containers run

    next_quick = next_slow = time.monotonic() + 20   # let the first collection settle
    token: str | None = None
    token_at = 0.0
    while not stop.is_set():
        now = time.monotonic()
        due = []
        if now >= next_slow:
            due, next_slow, next_quick = quick_round() + slow_round(), now + slow_seconds, now + quick_seconds
        elif now >= next_quick:
            due, next_quick = quick_round(), now + quick_seconds
        if due:
            try:
                if token is None or now - token_at > 3000:
                    token, token_at = _token(engine), now
                if token is None:
                    logger.warning("warm-up: no administrator account to ask as")
                else:
                    began, bad = time.monotonic(), 0
                    FORCE.on = True   # work every question out afresh and store it, whatever this process remembers
                    for path, query in due:
                        if stop.is_set():
                            break
                        status, _seconds = _call(web.application, token, path, query)
                        bad += status != 200
                    FORCE.on = False
                    logger.info("warm-up counts questions=%d not_ok=%d seconds=%.1f", len(due), bad, time.monotonic() - began)
            except Exception as exc:   # never let the warm-up take the collector down
                FORCE.on = False
                logger.warning("warm-up failed: %s", type(exc).__name__)
        stop.wait(2.0)
