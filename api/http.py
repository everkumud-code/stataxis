"""Minimal read-only HTTP handler for StatAxis intelligence."""

from __future__ import annotations

import json
from typing import Any, Callable

from sqlalchemy.orm import Session

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
    """Expose GET /api/v1/videos/{id}/intelligence without coupling to a web framework."""

    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "")
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
        body = json.dumps(payload).encode()
        start_response(f"{status} {reason}", [("Content-Type", "application/json")])
        return [body]

    return application
