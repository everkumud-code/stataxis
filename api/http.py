"""Minimal WSGI HTTP handler for the StatAxis API."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable
from urllib.parse import parse_qs

from sqlalchemy.orm import Session

from api.access import UserRole
from api.catalog import list_channels
from api.channel import channel_intelligence_comparison, channel_intelligence_overview, channel_view_series, compare_channels
from api.export import ObservationExportFilters, export_response
from api.intelligence import latest_video_intelligence
from api.media_intelligence import channel_media_intelligence, market_report
from api.operations import collection_health, intelligence_readiness
from api.report import channel_report
from api.signals import channel_signals


def get_video_intelligence(session: Session, video_id: int) -> tuple[int, dict[str, Any]]:
    if video_id <= 0:
        return 400, {"error": "video_id must be a positive integer"}
    payload = latest_video_intelligence(session, video_id)
    if payload is None:
        return 404, {"error": "intelligence not found"}
    return 200, payload


def get_channel_comparison(session: Session, channel_id: int, *, as_of: datetime | None = None) -> tuple[int, dict[str, Any]]:
    if channel_id <= 0:
        return 400, {"error": "channel_id must be a positive integer"}
    payload = channel_intelligence_comparison(session, channel_id, as_of=as_of)
    if payload is None:
        return 404, {"error": "channel not found"}
    return 200, payload


def get_channels_comparison(session: Session, channel_ids: list[int], *, as_of: datetime | None = None) -> tuple[int, dict[str, Any]]:
    if not channel_ids:
        return 400, {"error": "at least one channel_id is required"}
    if any(channel_id <= 0 for channel_id in channel_ids):
        return 400, {"error": "channel_id must be a positive integer"}
    if len(channel_ids) > 12:
        return 400, {"error": "a maximum of 12 channels can be compared"}
    return 200, compare_channels(session, channel_ids, as_of=as_of)


def get_collection_health(session: Session, *, as_of: datetime | None = None, stale_after_minutes: int = 360) -> tuple[int, dict[str, Any]]:
    try:
        payload = collection_health(session, as_of=as_of, stale_after_minutes=stale_after_minutes)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 200, payload


def get_intelligence_readiness(session: Session, *, as_of: datetime | None = None, stale_after_minutes: int = 360, min_snapshot_coverage: float = 1.0) -> tuple[int, dict[str, Any]]:
    try:
        payload = intelligence_readiness(session, as_of=as_of, stale_after_minutes=stale_after_minutes, min_snapshot_coverage=min_snapshot_coverage)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 200, payload


def get_channel_report(session: Session, channel_id: int, *, as_of: datetime | None = None, series_days: int = 30, signal_hours: int = 24) -> tuple[int, dict[str, Any]]:
    if channel_id <= 0:
        return 400, {"error": "channel_id must be a positive integer"}
    try:
        series_days = int(series_days)
        signal_hours = int(signal_hours)
    except (TypeError, ValueError):
        return 400, {"error": "series_days and signal_hours must be integers"}
    if not 1 <= series_days <= 365:
        return 400, {"error": "series_days must be between 1 and 365"}
    if not 1 <= signal_hours <= 168:
        return 400, {"error": "signal_hours must be between 1 and 168"}
    payload = channel_report(session, channel_id, as_of=as_of, series_days=series_days, signal_hours=signal_hours)
    if payload is None:
        return 404, {"error": "channel not found"}
    return 200, payload


def get_channel_media_intelligence(session: Session, channel_id: int, *, as_of: datetime | None = None, period: str = "7d", stream_scope: str = "all") -> tuple[int, dict[str, Any]]:
    if channel_id <= 0:
        return 400, {"error": "channel_id must be a positive integer"}
    try:
        payload = channel_media_intelligence(session, channel_id, as_of=as_of, period=period, stream_scope=stream_scope)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    if payload is None:
        return 404, {"error": "channel not found"}
    return 200, payload


def get_market_report(session: Session, *, as_of: datetime | None = None, period: str = "7d", language: str | None = None, region: str | None = None, market: str | None = None, stream_scope: str = "all", limit: int = 50) -> tuple[int, dict[str, Any]]:
    try:
        payload = market_report(session, as_of=as_of, period=period, language=language, region=region, market=market, stream_scope=stream_scope, limit=limit)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 200, payload


def get_channel_overview(session: Session, channel_id: int) -> tuple[int, dict[str, Any]]:
    if channel_id <= 0:
        return 400, {"error": "channel_id must be a positive integer"}
    payload = channel_intelligence_overview(session, channel_id)
    if payload is None:
        return 404, {"error": "channel not found"}
    return 200, payload


def get_channel_series(session: Session, channel_id: int, days: int = 30) -> tuple[int, dict[str, Any]]:
    if channel_id <= 0:
        return 400, {"error": "channel_id must be a positive integer"}
    try:
        days = int(days)
    except (TypeError, ValueError):
        return 400, {"error": "days must be an integer"}
    if not 1 <= days <= 365:
        return 400, {"error": "days must be between 1 and 365"}
    payload = channel_view_series(session, channel_id, days=days)
    if payload is None:
        return 404, {"error": "channel not found"}
    return 200, payload


def get_channel_signals(session: Session, channel_id: int, hours: int = 24) -> tuple[int, dict[str, Any]]:
    if channel_id <= 0:
        return 400, {"error": "channel_id must be a positive integer"}
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        return 400, {"error": "hours must be an integer"}
    payload = channel_signals(session, channel_id, window_hours=hours)
    if payload is None:
        return 404, {"error": "channel not found"}
    return 200, payload


def get_channel_catalog(session: Session) -> tuple[int, dict[str, Any]]:
    return 200, {"channels": list_channels(session)}


def wsgi_application(session_factory: Callable[[], Session]):
    """Expose health, catalog, intelligence, market, comparison, series, report and readiness endpoints."""
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "")
        if path == "/health":
            start_response("200 OK", [("Content-Type", "application/json")])
            return [b'{"status":"ok","service":"stataxis"}']
        if path == "/api/v1/channels":
            if method != "GET": return _json_response(start_response, 405, {"error": "method not allowed"})
            session = session_factory()
            try: status, payload = get_channel_catalog(session)
            finally: session.close()
            return _json_response(start_response, status, payload)
        if path == "/api/v1/markets/report":
            if method != "GET": return _json_response(start_response, 405, {"error": "method not allowed"})
            query = parse_qs(environ.get("QUERY_STRING", ""))
            try: as_of = _query_datetime(query, "as_of")
            except ValueError as exc: return _json_response(start_response, 400, {"error": str(exc)})
            session = session_factory()
            try:
                status, payload = get_market_report(session, as_of=as_of, period=query.get("period", ["7d"])[0], language=_optional_query(query, "language"), region=_optional_query(query, "region"), market=_optional_query(query, "market"), stream_scope=query.get("stream_scope", ["all"])[0], limit=query.get("limit", ["50"])[0])
            finally: session.close()
            return _json_response(start_response, status, payload)
        if path == "/api/v1/channels/compare":
            if method != "GET": return _json_response(start_response, 405, {"error": "method not allowed"})
            query = parse_qs(environ.get("QUERY_STRING", "")); raw_ids = query.get("ids", []); channel_ids: list[int] = []
            try:
                for raw in raw_ids: channel_ids.extend(int(part.strip()) for part in raw.split(",") if part.strip())
            except ValueError: return _json_response(start_response, 400, {"error": "ids must contain positive integer channel IDs"})
            try: as_of = _query_datetime(query, "as_of")
            except ValueError as exc: return _json_response(start_response, 400, {"error": str(exc)})
            session = session_factory()
            try: status, payload = get_channels_comparison(session, channel_ids, as_of=as_of)
            finally: session.close()
            return _json_response(start_response, status, payload)
        if path == "/api/v1/operations/collection":
            if method != "GET": return _json_response(start_response, 405, {"error": "method not allowed"})
            query = parse_qs(environ.get("QUERY_STRING", ""))
            try: as_of = _query_datetime(query, "as_of")
            except ValueError as exc: return _json_response(start_response, 400, {"error": str(exc)})
            try: stale_after_minutes = int(query.get("stale_after_minutes", ["360"])[0])
            except ValueError: return _json_response(start_response, 400, {"error": "stale_after_minutes must be an integer"})
            session = session_factory()
            try: status, payload = get_collection_health(session, as_of=as_of, stale_after_minutes=stale_after_minutes)
            finally: session.close()
            return _json_response(start_response, status, payload)
        if path == "/api/v1/operations/readiness":
            if method != "GET": return _json_response(start_response, 405, {"error": "method not allowed"})
            query = parse_qs(environ.get("QUERY_STRING", ""))
            try: as_of = _query_datetime(query, "as_of")
            except ValueError as exc: return _json_response(start_response, 400, {"error": str(exc)})
            try:
                stale_after_minutes = int(query.get("stale_after_minutes", ["360"])[0]); min_snapshot_coverage = float(query.get("min_snapshot_coverage", ["1.0"])[0])
            except ValueError: return _json_response(start_response, 400, {"error": "stale_after_minutes must be an integer and min_snapshot_coverage must be a number"})
            session = session_factory()
            try: status, payload = get_intelligence_readiness(session, as_of=as_of, stale_after_minutes=stale_after_minutes, min_snapshot_coverage=min_snapshot_coverage)
            finally: session.close()
            return _json_response(start_response, status, payload)
        if path == "/api/v1/reports/export": return _report_response(environ, start_response, session_factory, method)
        channel_prefix = "/api/v1/channels/"; report_suffix = "/report"
        if path.startswith(channel_prefix) and path.endswith(report_suffix):
            if method != "GET": return _json_response(start_response, 405, {"error": "method not allowed"})
            try: channel_id = int(path[len(channel_prefix) : -len(report_suffix)])
            except ValueError: return _json_response(start_response, 400, {"error": "channel_id must be a positive integer"})
            query = parse_qs(environ.get("QUERY_STRING", ""))
            try: as_of = _query_datetime(query, "as_of")
            except ValueError as exc: return _json_response(start_response, 400, {"error": str(exc)})
            session = session_factory()
            try: status, payload = get_channel_report(session, channel_id, as_of=as_of, series_days=query.get("series_days", ["30"])[0], signal_hours=query.get("signal_hours", ["24"])[0])
            finally: session.close()
            return _json_response(start_response, status, payload)
        media_suffix = "/media-intelligence"
        if path.startswith(channel_prefix) and path.endswith(media_suffix):
            if method != "GET": return _json_response(start_response, 405, {"error": "method not allowed"})
            try: channel_id = int(path[len(channel_prefix) : -len(media_suffix)])
            except ValueError: return _json_response(start_response, 400, {"error": "channel_id must be a positive integer"})
            query = parse_qs(environ.get("QUERY_STRING", ""))
            try: as_of = _query_datetime(query, "as_of")
            except ValueError as exc: return _json_response(start_response, 400, {"error": str(exc)})
            session = session_factory()
            try: status, payload = get_channel_media_intelligence(session, channel_id, as_of=as_of, period=query.get("period", ["7d"])[0], stream_scope=query.get("stream_scope", ["all"])[0])
            finally: session.close()
            return _json_response(start_response, status, payload)
        channel_suffix = "/comparison"
        if path.startswith(channel_prefix) and path.endswith(channel_suffix):
            if method != "GET": return _json_response(start_response, 405, {"error": "method not allowed"})
            try: channel_id = int(path[len(channel_prefix) : -len(channel_suffix)])
            except ValueError: return _json_response(start_response, 400, {"error": "channel_id must be a positive integer"})
            query = parse_qs(environ.get("QUERY_STRING", ""))
            try: as_of = _query_datetime(query, "as_of")
            except ValueError as exc: return _json_response(start_response, 400, {"error": str(exc)})
            session = session_factory()
            try: status, payload = get_channel_comparison(session, channel_id, as_of=as_of)
            finally: session.close()
            return _json_response(start_response, status, payload)
        series_suffix = "/series"
        if path.startswith(channel_prefix) and path.endswith(series_suffix):
            if method != "GET": return _json_response(start_response, 405, {"error": "method not allowed"})
            try: channel_id = int(path[len(channel_prefix) : -len(series_suffix)])
            except ValueError: return _json_response(start_response, 400, {"error": "channel_id must be a positive integer"})
            query = parse_qs(environ.get("QUERY_STRING", "")); raw_days = query.get("days", ["30"])[0]
            session = session_factory()
            try: status, payload = get_channel_series(session, channel_id, raw_days)
            finally: session.close()
            return _json_response(start_response, status, payload)
        signal_suffix = "/signals"
        if path.startswith(channel_prefix) and path.endswith(signal_suffix):
            if method != "GET": return _json_response(start_response, 405, {"error": "method not allowed"})
            try: channel_id = int(path[len(channel_prefix) : -len(signal_suffix)])
            except ValueError: return _json_response(start_response, 400, {"error": "channel_id must be a positive integer"})
            query = parse_qs(environ.get("QUERY_STRING", "")); raw_hours = query.get("hours", ["24"])[0]
            session = session_factory()
            try: status, payload = get_channel_signals(session, channel_id, raw_hours)
            finally: session.close()
            return _json_response(start_response, status, payload)
        if path.startswith(channel_prefix):
            if method != "GET": return _json_response(start_response, 405, {"error": "method not allowed"})
            try: channel_id = int(path[len(channel_prefix):])
            except ValueError: return _json_response(start_response, 400, {"error": "channel_id must be a positive integer"})
            session = session_factory()
            try: status, payload = get_channel_overview(session, channel_id)
            finally: session.close()
            return _json_response(start_response, status, payload)
        return _json_response(start_response, 404, {"error": "not found"})
    return application


def _optional_query(query: dict[str, list[str]], key: str) -> str | None:
    value = query.get(key, [""])[0].strip()
    return value or None


def _query_datetime(query: dict[str, list[str]], key: str) -> datetime | None:
    value = query.get(key, [""])[0].strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{key} must be a valid ISO-8601 datetime") from exc


def _json_response(start_response: Callable[..., Any], status: int, payload: dict[str, Any]):
    body = json.dumps(payload, default=str).encode("utf-8")
    start_response(f"{status} {HTTP_STATUS.get(status, 'OK')}", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]


HTTP_STATUS = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed", 500: "Internal Server Error"}


def _report_response(environ: dict[str, Any], start_response: Callable[..., Any], session_factory: Callable[[], Session], method: str):
    if method != "GET": return _json_response(start_response, 405, {"error": "method not allowed"})
    query = parse_qs(environ.get("QUERY_STRING", ""))
    try: as_of = _query_datetime(query, "as_of")
    except ValueError as exc: return _json_response(start_response, 400, {"error": str(exc)})
    try:
        filters = ObservationExportFilters.from_query(query)
    except ValueError as exc:
        return _json_response(start_response, 400, {"error": str(exc)})
    session = session_factory()
    try:
        return export_response(session, start_response, filters, as_of=as_of)
    finally:
        session.close()
