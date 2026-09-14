"""Minimal WSGI HTTP handler for the StatAxis API."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from api.access import UserRole
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


def wsgi_application(session_factory: Callable[[], Session]):
    """Expose health, intelligence and role-aware report endpoints."""

    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "")

        if path == "/health":
            body = b'{"status":"ok","service":"stataxis"}'
            start_response("200 OK", [("Content-Type", "application/json")])
            return [body]

        if path == "/api/v1/reports/export":
            return _report_response(environ, start_response, session_factory, method)

        prefix = "/api/v1/videos/"
        suffix = "/intelligence"
        if method != "GET" or not path.startswith(prefix) or not path.endswith(suffix):
            body = json.dumps({"error": "not found"}).encode()
            start_response("404 Not Found", [("Content-Type", "application/json")])
            return [body]

        raw_id = path[len(prefix) : -len(suffix)]
        try:
            video_id = int(raw_id)
        except ValueError:
            body = json.dumps({"error": "video_id must be a positive integer"}).encode()
            start_response("400 Bad Request", [("Content-Type", "application/json")])
            return [body]

        session = session_factory()
        try:
            status, payload = get_video_intelligence(session, video_id)
        finally:
            session.close()
        reason = {200: "OK", 400: "Bad Request", 404: "Not Found"}.get(status, "Error")
        start_response(f"{status} {reason}", [("Content-Type", "application/json")])
        return [json.dumps(payload).encode()]

    return application


def _report_response(environ: dict[str, Any], start_response: Callable[..., Any], session_factory, method: str):
    if method != "GET":
        start_response("405 Method Not Allowed", [("Content-Type", "application/json")])
        return [b'{"error":"method not allowed"}']

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


def _optional_header(environ: dict[str, Any], key: str) -> str | None:
    value = environ.get(key)
    return value.strip() if value and value.strip() else None
