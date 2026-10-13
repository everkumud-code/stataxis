"""The two things the public website may ask without signing in: a live pulse of the platform and the list of packages with what each includes.

Nothing here is a ranking or a channel's figure. The pulse is only counts that show the system is alive (how many channels are measured, how fresh the last measurement is, how many are live
right now); the packages are the plan names and the tools each plan includes. Answers are kept for a minute so the page cannot be used to load the database.
"""

from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Any, Callable

from sqlalchemy import func

from api import feature_access
from api.live_stats import FRESHNESS_SECONDS
from api.market_common import now_utc, utc
from api.methodology import methodology
from api.status import status_snapshot
from api.package_config import _payload as package_payload
from api.rate_limit import client_ip, limiter
from collector.storage import Channel, Observation, PackageConfig

_CACHE: dict[tuple[int, str], tuple[float, dict[str, Any]]] = {}
CACHE_SECONDS = 60


def _json(start_response: Callable[..., Any], status: int, payload: dict[str, Any], retry: int | None = None):
    body = json.dumps(payload).encode("utf-8")
    headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body))), ("Cache-Control", "public, max-age=30")]
    if retry:
        headers.append(("Retry-After", str(retry)))
    start_response({200: "200 OK", 404: "404 Not Found", 405: "405 Method Not Allowed", 429: "429 Too Many Requests"}[status], headers)
    return [body]


def pulse(session: Any) -> dict[str, Any]:
    now = now_utc()
    latest = session.query(func.max(Observation.observed_at)).scalar()
    live = session.query(func.count(func.distinct(Observation.channel_id))).filter(Observation.is_live.is_(True), Observation.observed_at >= now - timedelta(seconds=FRESHNESS_SECONDS)).scalar()
    return {"status": "online" if latest and (now - utc(latest)).total_seconds() < 1800 else "waiting", "channels_measured": session.query(Channel).filter(Channel.active.is_(True)).count(),
            "channels_live_now": int(live or 0), "last_measurement_minutes_ago": round((now - utc(latest)).total_seconds() / 60) if latest else None,
            "observations_stored": int(session.query(func.max(Observation.id)).scalar() or 0), "generated_at": now.isoformat()}


def packages(session: Any) -> dict[str, Any]:
    matrix = feature_access.matrix(session)
    priced = {p["name"]: p for p in (package_payload(r) for r in session.query(PackageConfig).filter(PackageConfig.active.is_(True)).order_by(PackageConfig.slot).all()) if p["name"]}
    return {"plans": feature_access.plans_overview(), "features": [{"feature": m["feature"], "label": m["label"], "description": feature_access.DESCRIPTIONS.get(m["feature"], ""), "min_plan": m["min_plan"]} for m in matrix],
            "order": feature_access.PLAN_ORDER, "commercial_packages": [{"name": p["name"], "criteria": p["criteria"], "amount": p["amount"], "currency": p["currency"]} for p in priced.values()]}


def public_application(session_factory: Callable[[], Any]):
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        path, method = environ.get("PATH_INFO", ""), environ.get("REQUEST_METHOD", "GET")
        if method != "GET":
            return _json(start_response, 405, {"error": "method not allowed"})
        if path not in {"/api/v1/public/pulse", "/api/v1/public/packages", "/api/v1/public/status", "/api/v1/public/methodology"}:
            return _json(start_response, 404, {"error": "not found"})
        retry = limiter.check(f"public:{client_ip(environ)}", 90, 60)
        if retry:
            return _json(start_response, 429, {"error": "too many requests"}, retry)
        key = (id(session_factory), path)   # the real site and the public demo each have their own answers
        hit = _CACHE.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return _json(start_response, 200, hit[1])
        session = session_factory()
        try:
            if path.endswith("/pulse"):
                data = pulse(session)
            elif path.endswith("/status"):
                data = status_snapshot(session)
            elif path.endswith("/methodology"):
                data = methodology()
            else:
                data = packages(session)
        finally:
            session.close()
        _CACHE[key] = (time.monotonic(), data)
        return _json(start_response, 200, data)

    return application
