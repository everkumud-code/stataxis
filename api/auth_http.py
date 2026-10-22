"""Account registration and login HTTP endpoints for StatAxis."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from sqlalchemy.orm import Session

from collector.storage import User

from api import mailer, recovery
from api.auth import verify_password
from api.auth_service import authenticate, change_password, clean_login_id, login, register
from api.errors import AuthenticationError
from api.rate_limit import client_ip, limiter

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def auth_application(session_factory: Callable[[], Session]):
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "")
        if path not in {"/api/v1/auth/register", "/api/v1/auth/login", "/api/v1/auth/change-password", "/api/v1/auth/forgot", "/api/v1/auth/reset", "/api/v1/auth/recovery-codes", "/api/v1/auth/recovery-status"}:
            return _json(start_response, 404, {"error": "not found"})
        if method != "POST":
            return _json(start_response, 405, {"error": "method not allowed"})
        if path.endswith(("/forgot", "/reset", "/recovery-codes", "/recovery-status")):
            return _recovery(path, environ, start_response, session_factory)
        if path.endswith("/change-password"):
            return _change_password(environ, start_response, session_factory)
        try:
            payload = _read_json(environ)
            email = _email(payload.get("email")) if path.endswith("/register") else clean_login_id(payload.get("email"))
            password = payload.get("password")
            if not isinstance(password, str):
                raise ValueError("password is required")
            ip = client_ip(environ)
            if path.endswith("/register"):
                retry = limiter.check(f"register:{ip}", 5, 3600)
            else:
                retry = limiter.check(f"login:{ip}:{email}", 10, 900)
            if retry:
                return _json(start_response, 429, {"error": "too many requests"}, retry)
            session = session_factory()
            try:
                if path.endswith("/register"):
                    result = register(session, email, password, payload.get("name", ""), payload.get("mobile", ""),
                                      payload.get("organization", ""), payload.get("purpose_of_use", ""),
                                      payload.get("requested_plan", ""))
                    if result.get("already_exists"):
                        result = {"message": "Profile submitted for admin approval."}
                    else:
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


def _recovery(path: str, environ: dict[str, Any], start_response: Callable[..., Any], session_factory: Callable[[], Session]):
    """Forgot password (asks for an e-mail code), reset with a code, and, for a signed-in person, making and counting backup codes."""
    try:
        ip = client_ip(environ)
        if path.endswith(("/recovery-codes", "/recovery-status")):
            try:
                identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
            except AuthenticationError:
                return _json(start_response, 401, {"error": "authentication required"})
            retry = limiter.check(f"recovery-codes:{identity.user_id}", 6, 900)
            if retry:
                return _json(start_response, 429, {"error": "too many requests"}, retry)
            payload = _read_json(environ)
            session = session_factory()
            try:
                user = session.get(User, identity.user_id)
                if user is None or not user.active:
                    return _json(start_response, 401, {"error": "authentication required"})
                if path.endswith("/recovery-status"):
                    return _json(start_response, 200, recovery.backup_status(session, user.id))
                if not isinstance(payload.get("current_password"), str) or not verify_password(payload["current_password"], user.password_hash):
                    return _json(start_response, 403, {"error": "current password is not correct"})   # a stolen open session alone cannot make codes
                codes = recovery.make_backup_codes(session, user.id)
                return _json(start_response, 200, {"codes": codes, "message": "Keep these codes somewhere safe. Each works once. They are shown only now."})
            finally:
                session.close()
        payload = _read_json(environ)
        login_id = clean_login_id(payload.get("login") if "login" in payload else payload.get("email"))
        if path.endswith("/forgot"):
            if limiter.check(f"forgot:{ip}", 6, 3600) or limiter.check(f"forgot-login:{login_id}", 3, 3600):
                return _json(start_response, 429, {"error": "too many requests; wait a while and try again"})
            session = session_factory()
            try:
                made = recovery.issue_email_code(session, login_id)
                if made is not None:
                    user, code = made
                    subject, html, text = recovery.email_text(code, user.email, mailer.settings(session)["base_url"])
                    recovery.send_in_background(session_factory, user.email, subject, html, text)
            finally:
                session.close()
            return _json(start_response, 200, {"message": recovery.SENT})   # the same answer for every login ID
        if limiter.check(f"reset:{ip}:{login_id}", 8, 900) or limiter.check(f"reset-login:{login_id}", 20, 3600):
            return _json(start_response, 429, {"error": "too many tries; wait a while and try again"})
        session = session_factory()
        try:
            recovery.reset_password(session, login_id, payload.get("code"), payload.get("new_password"))
        finally:
            session.close()
        return _json(start_response, 200, {"message": "Password changed. You can sign in with it now."})
    except PermissionError as exc:
        return _json(start_response, 403, {"error": str(exc)})
    except ValueError as exc:
        return _json(start_response, 400, {"error": str(exc)})


def _change_password(environ: dict[str, Any], start_response: Callable[..., Any], session_factory: Callable[[], Session]):
    """A signed-in account changes its own password: the bearer token says who, the current password proves it is really them."""
    try:
        identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
    except AuthenticationError:
        return _json(start_response, 401, {"error": "authentication required"})
    try:
        retry = limiter.check(f"change-password:{identity.user_id}", 5, 900)
        if retry:
            return _json(start_response, 429, {"error": "too many requests"}, retry)
        payload = _read_json(environ)
        session = session_factory()
        try:
            change_password(session, identity.user_id, payload.get("current_password"), payload.get("new_password"))
        finally:
            session.close()
        return _json(start_response, 200, {"message": "Password changed."})
    except PermissionError as exc:
        return _json(start_response, 403, {"error": str(exc)})
    except ValueError as exc:
        return _json(start_response, 400, {"error": str(exc)})


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


def _json(start_response: Callable[..., Any], status: int, payload: dict[str, Any], retry_after: int | None = None):
    reasons = {200: "OK", 201: "Created", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 429: "Too Many Requests"}
    body = json.dumps(payload).encode("utf-8")
    headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
    if retry_after is not None:
        headers.append(("Retry-After", str(retry_after)))
    start_response(f"{status} {reasons[status]}", headers)
    return [body]
