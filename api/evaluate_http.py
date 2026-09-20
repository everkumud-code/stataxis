"""HTTP adapter for authenticated manual YouTube evaluation."""

from __future__ import annotations

from api.errors import AuthenticationError, AuthorizationError
import json
from typing import Any, Callable

from sqlalchemy.orm import Session

from api.auth_service import authenticate
from api.evaluate import evaluate_youtube_url
from api.rate_limit import client_ip, limiter


def evaluate_application(session_factory: Callable[[], Session]):
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        if environ.get("REQUEST_METHOD") != "POST":
            return _json(start_response, 405, {"error": "method not allowed"})
        try:
            identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
            retry = limiter.check(f"evaluate-youtube:{getattr(identity, "user_id", "unknown")}:{client_ip(environ)}", 30, 3600)
            if retry:
                return _json(start_response, 429, {"error": "too many requests"}, retry)
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
        except AuthenticationError as exc:
            return _json(start_response, 401, {"error": str(exc)})
        except AuthorizationError as exc:
            return _json(start_response, 403, {"error": str(exc)})
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


def _json(start_response: Callable[..., Any], status: int, payload: dict[str, Any], retry_after: int | None = None):
    reasons = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 405: "Method Not Allowed", 429: "Too Many Requests"}
    body = json.dumps(payload).encode("utf-8")
    headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
    if retry_after is not None:
        headers.append(("Retry-After", str(retry_after)))
    start_response(f"{status} {reasons[status]}", headers)
    return [body]
