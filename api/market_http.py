"""HTTP endpoints for the market tools: weekly views, prime time, report builder (with PDF), IFX Score, media planner, authenticity radar and the quota need.

A signed-in account may use a tool when its package is high enough for that tool (an admin sets the lowest package for each tool, see api/feature_access.py).
The package is read from the account record on every request, so a change of package or switching an account off works at once, not when the old login runs out.
Only an admin can record a decision on an authenticity flag or open the quota page.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
from typing import Any, Callable
from urllib.parse import parse_qs

from api import audience as audience_mod
from api import authenticity, feature_access
from api.auth_service import authenticate
from api.errors import AuthenticationError, AuthorizationError
from api.market_common import today_ist
from api.market_tools import creator_scores, media_plan, prime_time, quota_need, weekly_views
from api.findings import briefing, briefing_as_report
from api.live_event import live_event_compare
from api.report_builder import build_report
from collector.storage import Channel, User

_REASONS = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed"}
ROUTE_FEATURE = {
    ("GET", "/api/v1/market/weekly"): "weekly",
    ("GET", "/api/v1/market/prime-time"): "prime_time",
    ("GET", "/api/v1/market/report"): "report_builder",
    ("GET", "/api/v1/market/report.pdf"): "report_builder",
    ("GET", "/api/v1/market/creators"): "creators",
    ("GET", "/api/v1/market/creator-index"): "creators",
    ("GET", "/api/v1/market/audience"): "audience",
    ("GET", "/api/v1/market/live-event"): "live_compare",
    ("GET", "/api/v1/market/briefing"): "briefing",
    ("GET", "/api/v1/market/briefing.pdf"): "report_builder",
    ("POST", "/api/v1/market/planner"): "planner",
    ("GET", "/api/v1/market/authenticity"): "authenticity",
    ("POST", "/api/v1/market/authenticity/review"): "authenticity",
}


def _json(start_response: Callable[..., Any], status: int, payload: dict[str, Any]):
    body = json.dumps(payload, default=str).encode("utf-8")
    start_response(f"{status} {_REASONS.get(status, 'OK')}", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]


def _read_json(environ: dict[str, Any], limit: int = 65_536) -> dict[str, Any]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError as exc:
        raise ValueError("invalid content length") from exc
    if length <= 0 or length > limit:
        raise ValueError(f"request body must be between 1 and {limit} bytes")
    try:
        payload = json.loads(environ["wsgi.input"].read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    return payload


def _num(value: Any, name: str, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc


def _int(value: Any, name: str, default: int) -> int:
    return int(_num(value, name, float(default)))


def _ids(raw: Any) -> list[int] | None:
    """Channel ids as comma-separated text (or a list): the 'individual channel(s)' filter."""
    if not raw:
        return None
    parts = raw.split(",") if isinstance(raw, str) else list(raw)
    try:
        ids = sorted({int(p) for p in parts if str(p).strip()})
    except (TypeError, ValueError) as exc:
        raise ValueError("channels must be channel numbers separated by commas") from exc
    if len(ids) > 200:
        raise ValueError("too many channels chosen")
    return ids or None


def market_application(session_factory: Callable[[], Any]):
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "GET")
        q = {k: v[0].strip() for k, v in parse_qs(environ.get("QUERY_STRING", "")).items() if v}
        try:
            identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
            session = session_factory()
            try:
                user = session.get(User, identity.user_id)
                if user is None or not user.active:
                    raise AuthenticationError("authentication required")
                feature = ROUTE_FEATURE.get((method, path))
                if feature and not feature_access.allowed(session, feature, user.plan, user.is_admin, user.id):
                    raise AuthorizationError(feature_access.explain_denied(session, feature, user.plan, user.id))
                segment, language = q.get("segment") or None, q.get("language") or None
                cids = _ids(q.get("channels") or q.get("channel_id"))
                target = audience_mod.parse_target(q.get("ages"), q.get("states"), q.get("gender"))
                profiles = audience_mod.profiles(session) if target["active"] else None
                known_only = q.get("known_only") in {"1", "true", "yes"}
                yesterday = today_ist() - timedelta(days=1)
                week_from, week_to = q.get("from") or (yesterday - timedelta(days=6)).isoformat(), q.get("to") or yesterday.isoformat()
                if (method, path) == ("GET", "/api/v1/market/weekly"):
                    return _json(start_response, 200, weekly_views(session, start_date=week_from, end_date=week_to, segment=segment, language=language, channel_ids=cids,
                                                                    target=target, profiles=profiles, known_only=known_only))
                if (method, path) == ("GET", "/api/v1/market/prime-time"):
                    return _json(start_response, 200, prime_time(session, start_date=week_from, end_date=week_to, language=language, segment=segment, channel_ids=cids,
                                                                   target=target, profiles=profiles, known_only=known_only))
                if (method, path) in {("GET", "/api/v1/market/report"), ("GET", "/api/v1/market/report.pdf")}:
                    report = build_report(session, start_date=week_from, end_date=week_to, start_hour=_int(q.get("start_hour"), "start_hour", 9), end_hour=_int(q.get("end_hour"), "end_hour", 12),
                                          start_time=q.get("start_time") or None, end_time=q.get("end_time") or None, whole_day=q.get("whole_day") in {"1", "true", "yes"}, day_wise=q.get("day_wise") in {"1", "true", "yes"},
                                          feed=q.get("feed") or "all", scope=q.get("scope") or "live", genre=q.get("genre") or None, language=language, segment=segment,
                                          by_genre=q.get("by_genre") in {"1", "true", "yes"}, channel_ids=cids, target=target, profiles=profiles, known_only=known_only)
                    if path.endswith(".pdf"):
                        from api.report_pdf import filename, report_pdf
                        report["prepared_for"] = user.email + (f" ({user.organization})" if user.organization else "")
                        body = report_pdf(report)
                        start_response("200 OK", [("Content-Type", "application/pdf"), ("Content-Disposition", f'attachment; filename="{filename(report)}"'), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
                        return [body]
                    return _json(start_response, 200, report)
                if (method, path) == ("POST", "/api/v1/market/screen-report.pdf"):
                    # a branded PDF of the screen the person is looking at: any screen, one tap. The figures are what their browser shows them; the letterhead and the download time are ours.
                    from api.report_pdf import clean_screen, screen_filename, screen_pdf
                    screen = clean_screen(_read_json(environ, 1_600_000))
                    body = screen_pdf(screen, user.email + (f" ({user.organization})" if user.organization else ""))
                    start_response("200 OK", [("Content-Type", "application/pdf"), ("Content-Disposition", f'attachment; filename="{screen_filename(screen)}"'), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
                    return [body]
                if (method, path) == ("GET", "/api/v1/market/creators"):
                    return _json(start_response, 200, creator_scores(session, segment=segment, language=language, days=_int(q.get("days"), "days", 30), channel_ids=cids))
                if (method, path) == ("GET", "/api/v1/market/creator-index"):
                    from api.creator_index import creator_index
                    return _json(start_response, 200, creator_index(session, segment=segment, language=language, days=_int(q.get("days"), "days", 30), channel_ids=cids))
                if (method, path) in {("GET", "/api/v1/market/briefing"), ("GET", "/api/v1/market/briefing.pdf")}:
                    b = briefing(session, persona=q.get("persona") or "buyer", days=_int(q.get("days"), "days", 7), segment=segment, language=language, channel_ids=cids)
                    if path.endswith(".pdf"):
                        from api.report_pdf import filename, report_pdf
                        rep = briefing_as_report(b)
                        rep["prepared_for"] = user.email + (f" ({user.organization})" if user.organization else "")
                        body = report_pdf(rep)
                        start_response("200 OK", [("Content-Type", "application/pdf"), ("Content-Disposition", f'attachment; filename="{filename(rep)}"'), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
                        return [body]
                    if feature_access.plan_rank(user.plan) < feature_access.plan_rank("sx_idea") and not user.is_admin:
                        # a free account sees the headlines and the first three findings; the evidence and what to do about it are for packages that include them
                        b["locked"] = True
                        b["findings"] = [{**f, "so_what": None, "evidence": {}, "detail": ""} for f in b["findings"][:3]]
                        b["upgrade"] = "The evidence behind each finding and what it means for you are part of SX Idea and above."
                    return _json(start_response, 200, b)
                if (method, path) == ("POST", "/api/v1/market/upgrade-request"):
                    body = _read_json(environ)
                    plan = str(body.get("plan") or "")
                    from api.plans import get_plan
                    code = get_plan(plan).code.value
                    if feature_access.plan_rank(code) <= feature_access.plan_rank(user.plan):
                        raise ValueError("choose a package higher than your own")
                    user.requested_plan = code
                    session.commit()
                    return _json(start_response, 200, {"requested_plan": code, "message": "Your request is with the STAXIS admin team."})
                if (method, path) == ("GET", "/api/v1/market/audience"):
                    return _json(start_response, 200, audience_mod.overview(session))
                if (method, path) == ("GET", "/api/v1/market/live-event"):
                    return _json(start_response, 200, live_event_compare(session, terms=[t for t in (q.get("terms") or "").split(",") if t.strip()], channel_ids=cids, minutes=_int(q.get("minutes"), "minutes", 60),
                                                                          segment=segment, language=language, stx_period=q.get("stx_period") or "7d", feed=q.get("feed") or "all"))
                if (method, path) == ("GET", "/api/v1/market/authenticity"):
                    return _json(start_response, 200, authenticity.scan(session, days=_int(q.get("days"), "days", 7), segment=segment, language=language, channel_ids=cids))
                if (method, path) == ("GET", "/api/v1/market/quota"):
                    if not user.is_admin:
                        raise AuthorizationError("admin access required")
                    count = session.query(Channel).filter(Channel.active.is_(True)).count()
                    extra = _int(q.get("extra_channels"), "extra_channels", 0)
                    collect = _int(q.get("collect_seconds"), "collect_seconds", int(os.getenv("COLLECT_SECONDS", "600")))
                    live = _int(q.get("live_poll_seconds"), "live_poll_seconds", int(os.getenv("LIVE_POLL_SECONDS", "30")))
                    return _json(start_response, 200, {"active_channels": count, "now": quota_need(count + extra, collect, live), "target": quota_need(count + extra, 600, 30)})
                if (method, path) == ("POST", "/api/v1/market/planner"):
                    body = _read_json(environ)
                    risk = authenticity.risk_by_channel(session, days=7, segment=body.get("segment") or None, language=body.get("language") or None) if body.get("check_authenticity", True) else {}
                    rates = {int(k): _num(v, "rate") for k, v in (body.get("rates") or {}).items()}
                    return _json(start_response, 200, media_plan(
                        session, start_hour=_int(body.get("start_hour"), "start_hour", 20), end_hour=_int(body.get("end_hour"), "end_hour", 22), days=_int(body.get("days"), "days", 7),
                        language=body.get("language") or None, segment=body.get("segment") or None, rates=rates, budget=_num(body.get("budget"), "budget"),
                        max_share=_num(body.get("max_share_percent"), "max_share_percent", 40) / 100, authenticity=risk, target=body.get("target") or None, profiles=audience_mod.profiles(session), channel_ids=_ids(body.get("channels"))))
                if (method, path) == ("POST", "/api/v1/market/authenticity/review"):
                    if not user.is_admin:
                        raise AuthorizationError("admin access required")
                    body = _read_json(environ)
                    return _json(start_response, 200, authenticity.set_review(session, channel_id=int(body.get("channel_id")), signal=str(body.get("signal") or ""), status=str(body.get("status") or ""),
                                                                              note=str(body.get("note") or ""), by=user.email))
                return _json(start_response, 404, {"error": "not found"})
            finally:
                session.close()
        except AuthenticationError as exc:
            return _json(start_response, 401, {"error": str(exc)})
        except (AuthorizationError, PermissionError) as exc:
            return _json(start_response, 403, {"error": str(exc)})
        except (ValueError, TypeError) as exc:
            return _json(start_response, 400, {"error": str(exc)})

    return application
