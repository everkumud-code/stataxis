"""Account application and login HTTP endpoints for StatAxis."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from sqlalchemy.orm import Session

from api.auth_service import login, register

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def auth_application(session_factory: Callable[[], Session]):
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "")
        if path not in {"/api/v1/auth/register", "/api/v1/auth/login"}:
            return _json(start_response, 404, {"error": "not found"})
        if method != "POST":
            return _json(start_response, 405, {"error": "method not allowed"})
        try:
            payload = _read_json(environ)
            email = _email(payload.get("email"))
            password = payload.get("password")
            if not isinstance(password, str):
                raise ValueError("password is required")
            session = session_factory()
            try:
                if path.endswith("/register"):
                    result = register(session, email, password, payload.get("name", ""), payload.get("mobile", ""),
                                      payload.get("organization", ""), payload.get("purpose_of_use", ""),
                                      payload.get("requested_plan", ""))
                    result = {"account": result, "message": "Profile submitted for admin approval."}
                    status = 201
                else:
                    result = login(session, email, password)
                    status = 200
            finally:
                session.close()
            return _json(start_response, status, result)
        except PermissionError as exc:
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
    raw = environ.get("wsgi.input").read(length)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    return payload


def _email(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("email is required")
    email = value.strip().lower()
    if len(email) > 320 or not EMAIL_RE.fullmatch(email):
        raise ValueError("invalid email")
    return email


def _json(start_response: Callable[..., Any], status: int, payload: dict[str, Any]):
    reasons = {200: "OK", 201: "Created", 400: "Bad Request", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed"}
    body = json.dumps(payload).encode("utf-8")
    start_response(f"{status} {reasons[status]}", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]
