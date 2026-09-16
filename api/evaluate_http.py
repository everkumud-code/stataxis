"""HTTP adapter for authenticated manual YouTube evaluation."""

from __future__ import annotations

import json
from typing import Any, Callable

from sqlalchemy.orm import Session

from api.auth_service import authenticate
from api.evaluate import evaluate_youtube_url


def evaluate_application(session_factory: Callable[[], Session]):
    """Expose POST /api/v1/evaluate/youtube with bearer authentication."""

    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        if environ.get("REQUEST_METHOD") != "POST":
            return _json(start_response, 405, {"error": "method not allowed"})
        try:
            identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
            payload = _read_json(environ)
            url = payload.get("url")
            display_name = payload.get("display_name")
            if not isinstance(url, str) or not url.strip():
                raise ValueError("url is required")
            if not isinstance(display_name, str) or not display_name.strip():
                raise ValueError("display_name is required")
            session = session_factory()
            try:
                result = evaluate_youtube_url(session, identity, url, display_name)
            finally:
                session.close()
            return _json(start_response, 200, result.as_dict())
        except PermissionError as exc:
            message = str(exc)
            status = 403 if "can_evaluate" in message else 401
            return _json(start_response, status, {"error": message})
        except ValueError as exc:
            return _json(start_response, 400, {"error": str(exc)})

    return application


def _read_json(environ: dict[str, Any]) -> dict[str, Any]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError as exc:
        raise ValueError("invalid content length") from exc
    if length <= 0 or length > 16_384:
        raise ValueError("request body must be between 1 and 16384 bytes")
    stream = environ.get("wsgi.input")
    if stream is None:
        raise ValueError("request body is required")
    try:
        payload = json.loads(stream.read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    return payload


def _json(start_response: Callable[..., Any], status: int, payload: dict[str, Any]):
    reasons = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 405: "Method Not Allowed"}
    body = json.dumps(payload).encode("utf-8")
    start_response(
        f"{status} {reasons[status]}",
        [("Content-Type", "application/json"), ("Content-Length", str(len(body)))],
    )
    return [body]
