"""Account registration and login HTTP endpoints for StatAxis."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from sqlalchemy.orm import Session

from api.auth import AuthIdentity, hash_password, issue_token, verify_password
from api.plans import SXPlan, get_plan
from collector.storage import User

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def auth_application(session_factory: Callable[[], Session]):
    """Expose register/login endpoints with server-side SX plan assignment."""

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
                    result = _register(session, email, password)
                    status = 201
                else:
                    result = _login(session, email, password)
                    status = 200
            finally:
                session.close()
            return _json(start_response, status, result)
        except ValueError as exc:
            return _json(start_response, 400, {"error": str(exc)})

    return application


def _register(session: Session, email: str, password: str) -> dict[str, Any]:
    existing = session.query(User).filter_by(email=email).one_or_none()
    if existing is not None:
        raise ValueError("account already exists")
    user = User(email=email, password_hash=hash_password(password), plan=SXPlan.FREE.value)
    session.add(user)
    session.commit()
    identity = AuthIdentity(user.id, user.email, user.plan, user.is_admin)
    return {"user": _user_payload(user), "access_token": issue_token(identity), "token_type": "Bearer"}


def _login(session: Session, email: str, password: str) -> dict[str, Any]:
    user = session.query(User).filter_by(email=email, active=True).one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise ValueError("invalid email or password")
    identity = AuthIdentity(user.id, user.email, user.plan, user.is_admin)
    return {"user": _user_payload(user), "access_token": issue_token(identity), "token_type": "Bearer"}


def _user_payload(user: User) -> dict[str, Any]:
    definition = get_plan(user.plan)
    return {
        "id": user.id,
        "email": user.email,
        "plan": definition.code.value,
        "plan_name": definition.name,
        "is_admin": user.is_admin,
    }


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
    reasons = {200: "OK", 201: "Created", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed"}
    body = json.dumps(payload).encode("utf-8")
    start_response(f"{status} {reasons[status]}", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]
