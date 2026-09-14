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


def get_intelligence_readiness(
    session: Session,
    *,
    as_of: datetime | None = None,
    stale_after_minutes: int = 360,
    min_snapshot_coverage: float = 1.0,
) -> tuple[int, dict[str, Any]]:
    try:
        payload = intelligence_readiness(
            session,
            as_of=as_of,
            stale_after_minutes=stale_after_minutes,
            min_snapshot_coverage=min_snapshot_coverage,
        )
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 200, payload


def get_channel_report(
    session: Session,
    channel_id: int,
    *,
    as_of: datetime | None = None,
    series_days: int = 30,
    signal_hours: int = 24,
) -> tuple[int, dict[str, Any]]:
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
    payload = channel_report(
        session,
        channel_id,
        as_of=as_of,
        series_days=series_days,
        signal_hours=signal_hours,
    )
    if payload is None:
        return 404, {"error": "channel not found"}
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
    """Expose health, catalog, intelligence, signal, comparison, series, report and readiness endpoints."""

    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "")

        if path == "/health":
            start_response("200 OK", [("Content-Type", "application/json")])
            return [b'{"status":"ok","service":"stataxis"}']

        if path == "/api/v1/channels":
            if method != "GET":
                return _json_response(start_response, 405, {"error": "method not allowed"})
            session = session_factory()
            try:
                status, payload = get_channel_catalog(session)
            finally:
                session.close()
            return _json_response(start_response, status, payload)

        if path == "/api/v1/channels/compare":
            if method != "GET":
                return _json_response(start_response, 405, {"error": "method not allowed"})
            query = parse_qs(environ.get("QUERY_STRING", ""))
            raw_ids = query.get("ids", [])
            channel_ids: list[int] = []
            try:
                for raw in raw_ids:
                    channel_ids.extend(int(part.strip()) for part in raw.split(",") if part.strip())
            except ValueError:
                return _json_response(start_response, 400, {"error": "ids must contain positive integer channel IDs"})
            try:
                as_of = _query_datetime(query, "as_of")
            except ValueError as exc:
                return _json_response(start_response, 400, {"error": str(exc)})
            session = session_factory()
            try:
                status, payload = get_channels_comparison(session, channel_ids, as_of=as_of)
            finally:
                session.close()
            return _json_response(start_response, status, payload)

        if path == "/api/v1/operations/collection":
            if method != "GET":
                return _json_response(start_response, 405, {"error": "method not allowed"})
            query = parse_qs(environ.get("QUERY_STRING", ""))
            try:
                as_of = _query_datetime(query, "as_of")
            except ValueError as exc:
                return _json_response(start_response, 400, {"error": str(exc)})
            raw_stale = query.get("stale_after_minutes", ["360"])[0]
            try:
                stale_after_minutes = int(raw_stale)
            except ValueError:
                return _json_response(start_response, 400, {"error": "stale_after_minutes must be an integer"})
            session = session_factory()
            try:
                status, payload = get_collection_health(session, as_of=as_of, stale_after_minutes=stale_after_minutes)
            finally:
                session.close()
            return _json_response(start_response, status, payload)

        if path == "/api/v1/operations/readiness":
            if method != "GET":
                return _json_response(start_response, 405, {"error": "method not allowed"})
            query = parse_qs(environ.get("QUERY_STRING", ""))
            try:
                as_of = _query_datetime(query, "as_of")
            except ValueError as exc:
                return _json_response(start_response, 400, {"error": str(exc)})
            raw_stale = query.get("stale_after_minutes", ["360"])[0]
            raw_coverage = query.get("min_snapshot_coverage", ["1.0"])[0]
            try:
                stale_after_minutes = int(raw_stale)
                min_snapshot_coverage = float(raw_coverage)
            except ValueError:
                return _json_response(start_response, 400, {"error": "stale_after_minutes must be an integer and min_snapshot_coverage must be a number"})
            session = session_factory()
            try:
                status, payload = get_intelligence_readiness(
                    session,
                    as_of=as_of,
                    stale_after_minutes=stale_after_minutes,
                    min_snapshot_coverage=min_snapshot_coverage,
                )
            finally:
                session.close()
            return _json_response(start_response, status, payload)

        if path == "/api/v1/reports/export":
            return _report_response(environ, start_response, session_factory, method)

        channel_prefix = "/api/v1/channels/"
        report_suffix = "/report"
        if path.startswith(channel_prefix) and path.endswith(report_suffix):
            if method != "GET":
                return _json_response(start_response, 405, {"error": "method not allowed"})
            raw_id = path[len(channel_prefix) : -len(report_suffix)]
            try:
                channel_id = int(raw_id)
            except ValueError:
                return _json_response(start_response, 400, {"error": "channel_id must be a positive integer"})
            query = parse_qs(environ.get("QUERY_STRING", ""))
            try:
                as_of = _query_datetime(query, "as_of")
            except ValueError as exc:
                return _json_response(start_response, 400, {"error": str(exc)})
            raw_series_days = query.get("series_days", ["30"])[0]
            raw_signal_hours = query.get("signal_hours", ["24"])[0]
            session = session_factory()
            try:
                status, payload = get_channel_report(
                    session,
                    channel_id,
                    as_of=as_of,
                    series_days=raw_series_days,
                    signal_hours=raw_signal_hours,
                )
            finally:
                session.close()
            return _json_response(start_response, status, payload)

        channel_suffix = "/comparison"
        if path.startswith(channel_prefix) and path.endswith(channel_suffix):
            if method != "GET":
                return _json_response(start_response, 405, {"error": "method not allowed"})
            raw_id = path[len(channel_prefix) : -len(channel_suffix)]
            try:
                channel_id = int(raw_id)
            except ValueError:
                return _json_response(start_response, 400, {"error": "channel_id must be a positive integer"})
            query = parse_qs(environ.get("QUERY_STRING", ""))
            try:
                as_of = _query_datetime(query, "as_of")
            except ValueError as exc:
                return _json_response(start_response, 400, {"error": str(exc)})
            session = session_factory()
            try:
                status, payload = get_channel_comparison(session, channel_id, as_of=as_of)
            finally:
                session.close()
            return _json_response(start_response, status, payload)

        series_suffix = "/series"
        if path.startswith(channel_prefix) and path.endswith(series_suffix):
            if method != "GET":
                return _json_response(start_response, 405, {"error": "method not allowed"})
            raw_id = path[len(channel_prefix) : -len(series_suffix)]
            try:
                channel_id = int(raw_id)
            except ValueError:
                return _json_response(start_response, 400, {"error": "channel_id must be a positive integer"})
            query = parse_qs(environ.get("QUERY_STRING", ""))
            raw_days = query.get("days", ["30"])[0]
            session = session_factory()
            try:
                status, payload = get_channel_series(session, channel_id, raw_days)
            finally:
                session.close()
            return _json_response(start_response, status, payload)

        signal_suffix = "/signals"
        if path.startswith(channel_prefix) and path.endswith(signal_suffix):
            if method != "GET":
                return _json_response(start_response, 405, {"error": "method not allowed"})
            raw_id = path[len(channel_prefix) : -len(signal_suffix)]
            try:
                channel_id = int(raw_id)
            except ValueError:
                return _json_response(start_response, 400, {"error": "channel_id must be a positive integer"})
            query = parse_qs(environ.get("QUERY_STRING", ""))
            raw_hours = query.get("hours", ["24"])[0]
            session = session_factory()
            try:
                status, payload = get_channel_signals(session, channel_id, raw_hours)
            finally:
                session.close()
            return _json_response(start_response, status, payload)

        if path.startswith(channel_prefix):
            if method != "GET":
                return _json_response(start_response, 404, {"error": "not found"})
            raw_id = path[len(channel_prefix) :].strip("/")
            if not raw_id or "/" in raw_id:
                return _json_response(start_response, 400, {"error": "channel_id must be a positive integer"})
            try:
                channel_id = int(raw_id)
            except ValueError:
                return _json_response(start_response, 400, {"error": "channel_id must be a positive integer"})
            session = session_factory()
            try:
                status, payload = get_channel_overview(session, channel_id)
            finally:
                session.close()
            return _json_response(start_response, status, payload)

        prefix = "/api/v1/videos/"
        suffix = "/intelligence"
        if method != "GET" or not path.startswith(prefix) or not path.endswith(suffix):
            return _json_response(start_response, 404, {"error": "not found"})

        raw_id = path[len(prefix) : -len(suffix)]
        try:
            video_id = int(raw_id)
        except ValueError:
            return _json_response(start_response, 400, {"error": "video_id must be a positive integer"})
        session = session_factory()
        try:
            status, payload = get_video_intelligence(session, video_id)
        finally:
            session.close()
        return _json_response(start_response, status, payload)

    return application


def _query_datetime(query: dict[str, list[str]], key: str) -> datetime | None:
    values = query.get(key)
    if not values or not values[0].strip():
        return None
    try:
        return datetime.fromisoformat(values[0].strip())
    except ValueError as exc:
        raise ValueError(f"{key} must be an ISO datetime") from exc


def _report_response(environ: dict[str, Any], start_response: Callable[..., Any], session_factory, method: str):
    if method != "GET":
        return _json_response(start_response, 405, {"error": "method not allowed"})

    def parse_datetime(name: str):
        value = environ.get(name)
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(f"invalid ISO datetime: {value}")

    role = environ.get("HTTP_X_STATAXIS_ROLE", UserRole.FREE.value)
    session = session_factory()
    try:
        filters = ObservationExportFilters(
            start_at=parse_datetime("HTTP_X_STATAXIS_START_AT"),
            end_at=parse_datetime("HTTP_X_STATAXIS_END_AT"),
            language=_optional_header(environ, "HTTP_X_STATAXIS_LANGUAGE"),
            region=_optional_header(environ, "HTTP_X_STATAXIS_REGION"),
        )
        status, headers, body = export_response(session, role, filters)
    except ValueError as exc:
        status, headers, body = 400, {"Content-Type": "application/json"}, json.dumps({"error": str(exc)}).encode()
    finally:
        session.close()

    reason = {200: "OK", 400: "Bad Request", 403: "Forbidden"}.get(status, "Error")
    start_response(f"{status} {reason}", list(headers.items()))
    return [body]


def _json_response(start_response: Callable[..., Any], status: int, payload: dict[str, Any]):
    reason = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed"}.get(status, "Error")
    start_response(f"{status} {reason}", [("Content-Type", "application/json")])
    return [json.dumps(payload).encode()]


def _optional_header(environ: dict[str, Any], key: str) -> str | None:
    value = environ.get(key)
    return value.strip() if value and value.strip() else None
