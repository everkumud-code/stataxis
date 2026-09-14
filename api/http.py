"""Minimal WSGI HTTP handler for the StatAxis API."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from api.access import UserRole
from api.catalog import list_channels
from api.channel import channel_intelligence_comparison, channel_intelligence_overview
from api.export import ObservationExportFilters, export_response
from api.intelligence import latest_video_intelligence


def get_video_intelligence(session: Session, video_id: int) -> tuple[int, dict[str, Any]]:
    """Return HTTP status and JSON-serializable payload for a video."""
    if video_id <= 0:
        return 400, {"error": "video_id must be a positive integer"}
    payload = latest_video_intelligence(session, video_id)
    if payload is None:
        return 404, {"error": "intelligence not found"}
    return 200, payload


def get_channel_comparison(session: Session, channel_id: int) -> tuple[int, dict[str, Any]]:
    """Return historical STX comparison for a channel."""
    if channel_id <= 0:
        return 400, {"error": "channel_id must be a positive integer"}
    payload = channel_intelligence_comparison(session, channel_id)
    if payload is None:
        return 404, {"error": "channel not found"}
    return 200, payload


def get_channel_overview(session: Session, channel_id: int) -> tuple[int, dict[str, Any]]:
    """Return latest scored videos for a channel."""
    if channel_id <= 0:
        return 400, {"error": "channel_id must be a positive integer"}
    payload = channel_intelligence_overview(session, channel_id)
    if payload is None:
        return 404, {"error": "channel not found"}
    return 200, payload


def get_channel_catalog(session: Session) -> tuple[int, dict[str, Any]]:
    """Return active channel metadata for dashboard selectors."""
    return 200, {"channels": list_channels(session)}


def wsgi_application(session_factory: Callable[[], Session]):
    """Expose health, catalog, intelligence and role-aware report endpoints."""

    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "")

        if path == "/health":
            body = b'{"status":"ok","service":"stataxis"}'
            start_response("200 OK", [("Content-Type", "application/json")])
            return [body]

        if path == "/api/v1/channels":
            if method != "GET":
                return _json_response(start_response, 405, {"error": "method not allowed"})
            session = session_factory()
            try:
                status, payload = get_channel_catalog(session)
            finally:
                session.close()
            return _json_response(start_response, status, payload)

        if path == "/api/v1/reports/export":
            return _report_response(environ, start_response, session_factory, method)

        channel_prefix = "/api/v1/channels/"
        channel_suffix = "/comparison"
        if path.startswith(channel_prefix) and path.endswith(channel_suffix):
            if method != "GET":
                return _json_response(start_response, 405, {"error": "method not allowed"})
            raw_id = path[len(channel_prefix) : -len(channel_suffix)]
            try:
                channel_id = int(raw_id)
            except ValueError:
                return _json_response(start_response, 400, {"error": "channel_id must be a positive integer"})
            session = session_factory()
            try:
                status, payload = get_channel_comparison(session, channel_id)
            finally:
                session.close()
            return _json_response(start_response, status, payload)

        if path.startswith(channel_prefix):
            if method != "GET":
                return _json_response(start_response, 405, {"error": "method not allowed"})
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
