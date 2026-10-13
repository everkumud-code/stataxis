"""Keeps the heavy screens' answers ready: asks the questions people ask most, over and over, and stores the finished answers (api/ttl_cache.py, table stx_snapshots).

It asks through the real web application (an in-process call, with a token for the administrator account), so what it stores is exactly what a person's screen would have asked for.
Three rounds: the short windows (last hour, 3 hours, 6 hours, today) and the spikes every 2.5 minutes, the analysis screens every 8 minutes, and every 10 minutes the extras (the biggest channels' own screens, the
report builder for yesterday, the media planner's usual slots, the other spike windows). It runs in the collector's container, which has the lower CPU share, so a
busy moment on the web screens always comes first. Off unless STAXIS_SNAPSHOT_SECONDS is above zero.
"""

from __future__ import annotations

import io
import json
import logging
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
    calls += [("/api/v1/market/weekly", week), ("/api/v1/market/prime-time", week), ("/api/v1/market/authenticity", "days=7"), ("/api/v1/market/creator-index", "days=30")] + [("/api/v1/market/creator-index", f"segment={seg}&days=30") for seg in ("creator", "journalist", "commentator")]
    calls += [("/api/v1/market/briefing", _q(persona=persona, days=7, language=lang)) for persona in PERSONAS for lang in LANGUAGES]
    return calls


def top_channel_ids(engine: Any, count: int = 10) -> list[int]:
    """The channels people are most likely to open: the biggest live audiences right now, padded with the first channels in the list."""
    from sqlalchemy.orm import Session

    from api.alerts import totals_at
    from collector.storage import Channel

    with Session(engine) as session:
        live = sorted(totals_at(session, datetime.now(UTC)).items(), key=lambda item: item[1], reverse=True)
        ids = [cid for cid, _ in live if session.get(Channel, cid) is not None and session.get(Channel, cid).active][:count]
        for (cid,) in session.query(Channel.id).filter(Channel.active.is_(True)).order_by(Channel.id):
            if len(ids) >= count:
                break
            if cid not in ids:
                ids.append(cid)
        return ids


def extra_round(engine: Any) -> list[tuple[str, str]]:
    """Everything else a person is likely to ask for next: the biggest channels' own screens, the report builder for yesterday's evening and the default week, the media planner's usual slots,
    and the other windows of the spikes screen. A request is ("POST /path", body) when it is sent as a form."""
    today = datetime.now(IST).date()
    yesterday = today - timedelta(days=1)
    day = yesterday.isoformat()
    calls: list[tuple[str, str]] = []
    for rank, channel_id in enumerate(top_channel_ids(engine, 10)):
        base = f"/api/v1/channels/{channel_id}"
        calls += [(f"{base}/overview", ""), (f"{base}/stx-trend", "days=30"), (f"{base}/series", "days=7"), (f"{base}/media-intelligence", "period=7d&stream_scope=all")]
        if rank < 4:
            calls += [(f"{base}/media-intelligence", "period=today&stream_scope=all"), (f"{base}/media-intelligence", "period=1h&stream_scope=all")]
    week = _q(**{"from": (yesterday - timedelta(days=6)).isoformat(), "to": day})
    calls.append(("/api/v1/market/report", f"{week}&start_hour=9&end_hour=12&scope=live&feed=all"))
    for start, end in ((19, 22), (17, 23), (9, 12)):
        for feed in ("all", "primary"):
            for lang in LANGUAGES:
                calls.append(("/api/v1/market/report", _q(**{"from": day, "to": day, "start_hour": start, "end_hour": end, "scope": "live", "feed": feed, "language": lang})))
    for start, end in ((20, 22), (19, 22), (21, 23), (18, 23)):
        for lang in LANGUAGES:
            body = {"start_hour": start, "end_hour": end, "days": 7, "segment": "", "language": lang, "budget": None, "max_share_percent": 40, "rates": {}, "channels": "", "target": None}
            calls.append(("POST /api/v1/market/planner", json.dumps(body)))
    calls += [("/api/v1/lab/spikes", f"hours={h}") for h in (1, 3, 12, 24)] + [("/api/v1/lab/movement", f"minutes={m}") for m in (15, 60, 120)] + [("/api/v1/lab/completeness", f"days={d}") for d in (1, 7)]
    return calls


def _call(app: Any, token: str, path: str, query: str) -> tuple[int, float]:
    out: dict[str, Any] = {}
    method, body = "GET", b""
    if path.startswith("POST "):
        method, path, body = "POST", path[5:], query.encode("utf-8")
        query = ""
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "wsgi.input": io.BytesIO(body), "CONTENT_LENGTH": str(len(body)), "REMOTE_ADDR": "127.0.0.1", "HTTP_AUTHORIZATION": "Bearer " + token,
               "CONTENT_TYPE": "application/json"}
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


def warm_forever(engine: Any, stop: Event, *, quick_seconds: int = 150, slow_seconds: int = 480, extra_seconds: int = 600) -> None:
    from api.ttl_cache import FORCE, snapshot_seconds

    if snapshot_seconds() <= 0:
        logger.info("warm-up loop off (STAXIS_SNAPSHOT_SECONDS is not set)")
        return
    import web   # the same application the web containers run

    next_quick = next_slow = time.monotonic() + 20   # let the first collection settle
    next_extra = time.monotonic() + 240              # the third round starts between the other two
    token: str | None = None
    token_at = 0.0
    while not stop.is_set():
        now = time.monotonic()
        due = []
        if now >= next_slow:
            due, next_slow, next_quick = quick_round() + slow_round(), now + slow_seconds, now + quick_seconds
        elif now >= next_extra:
            due, next_extra = extra_round(engine), now + extra_seconds
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
