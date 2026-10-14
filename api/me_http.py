"""HTTP endpoints for a person's own account (/api/v1/me...): who they are, what they may see and chose to see, and their profile."""

from __future__ import annotations

import json
from typing import Any, Callable

from api import dashboard_layout, me
from api.auth_service import authenticate
from api.errors import AuthenticationError
from collector.storage import User

_REASONS = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 404: "Not Found", 405: "Method Not Allowed"}


def _json(start_response: Callable[..., Any], status: int, payload: dict[str, Any]):
    body = json.dumps(payload, default=str).encode("utf-8")
    start_response(f"{status} {_REASONS.get(status, 'OK')}", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]


def _body(environ: dict[str, Any]) -> dict[str, Any]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError as exc:
        raise ValueError("invalid content length") from exc
    if length <= 0 or length > 16_384:
        raise ValueError("request body must be between 1 and 16384 bytes")
    try:
        data = json.loads(environ["wsgi.input"].read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("request body must be valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("request body must be a JSON object")
    return data


def me_application(session_factory: Callable[[], Any]):
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        path, method = environ.get("PATH_INFO", ""), environ.get("REQUEST_METHOD", "GET")
        try:
            identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
            session = session_factory()
            try:
                user = session.get(User, identity.user_id)
                if user is None or not user.active:
                    raise AuthenticationError("authentication required")
                if (method, path) == ("GET", "/api/v1/me"):
                    return _json(start_response, 200, me.me_payload(session, user))
                if (method, path) == ("GET", "/api/v1/me/dashboard"):
                    return _json(start_response, 200, dashboard_layout.get_layout(session, user))
                if (method, path) == ("POST", "/api/v1/me/dashboard"):
                    return _json(start_response, 200, dashboard_layout.save_layout(session, user, _body(environ)))
                if (method, path) == ("POST", "/api/v1/me/preferences"):
                    return _json(start_response, 200, me.set_preferences(session, user, _body(environ)))
                if (method, path) == ("POST", "/api/v1/me/profile"):
                    return _json(start_response, 200, me.update_profile(session, user, _body(environ)))
                return _json(start_response, 404 if path.startswith("/api/v1/me") else 405, {"error": "not found"})
            finally:
                session.close()
        except AuthenticationError as exc:
            return _json(start_response, 401, {"error": str(exc)})
        except PermissionError as exc:
            return _json(start_response, 401, {"error": str(exc)})
        except (ValueError, TypeError) as exc:
            return _json(start_response, 400, {"error": str(exc)})

    return application
