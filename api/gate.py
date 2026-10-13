"""The gate in front of the signed-in APIs: a password that must be changed first, and the screens a person may not use.

  * An account made or reset by an administrator carries a temporary password. Until the person has chosen their own, every call except "who am I" and the password change itself is refused.
  * Some screens have data of their own that no other screen shares (operations, the live audience, checking a video, the Excel export). For those the server refuses a person who may not use them,
    whatever the browser asks. The other screens read data that several screens share, so for those the person's list of screens decides what they are offered.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from api import feature_access
from api.auth_service import authenticate
from api.rate_limit import limiter
from collector.storage import User

import os

EXEMPT_UNTIL_PASSWORD_CHANGED = {("GET", "/api/v1/me")}
API_PER_MINUTE = int(os.getenv("STAXIS_API_PER_MINUTE", "600") or 600)
ADMIN_ONLY_PREFIXES: tuple[str, ...] = ()
FEATURE_RULES = (("/api/v1/operations/", ["operations", "integrity"]), ("/api/v1/evaluate/", ["evaluate"]), ("/api/v1/audience/live", ["live"]), ("/api/v1/reports/export", ["data_export"]),
                 ("/api/v1/insights/", ["overview", "changed", "research", "dashboard"]))   # these screens share one source: any of them is enough


def _json(start_response: Callable[..., Any], status: str, payload: dict[str, Any]):
    body = json.dumps(payload).encode("utf-8")
    start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]


def gate_application(session_factory: Callable[[], Any], downstream: Callable[..., Any]):
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        path, method = environ.get("PATH_INFO", ""), environ.get("REQUEST_METHOD", "GET")
        if not path.startswith("/api/v1/") or path.startswith(("/api/v1/auth/", "/api/v1/public/")):
            return downstream(environ, start_response)
        try:
            identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
        except Exception:
            return downstream(environ, start_response)   # the API itself answers 401
        session = session_factory()
        try:
            user = session.get(User, identity.user_id)
            if user is None or not user.active:
                # a valid signature is not enough: the account must exist and be switched on today (a removed or switched-off person, or a token made for another database, is refused)
                return _json(start_response, "401 Unauthorized", {"error": "authentication required"})
            retry = limiter.check(f"api:{user.id}", API_PER_MINUTE, 60)   # one person cannot take the server for everyone: about ten calls a second is far more than any screen needs
            if retry:
                return _json(start_response, "429 Too Many Requests", {"error": "too many requests; wait a moment", "retry_after_seconds": retry})
            if user.must_change_password and (method, path) not in EXEMPT_UNTIL_PASSWORD_CHANGED:
                return _json(start_response, "403 Forbidden", {"error": "choose your own password first", "code": "password_change_required"})
            if path.startswith(ADMIN_ONLY_PREFIXES) and not user.is_admin:
                return _json(start_response, "403 Forbidden", {"error": "admin access required"})
            for prefix, features in FEATURE_RULES:
                if path.startswith(prefix):
                    if not any(feature_access.allowed(session, f, user.plan, user.is_admin, user.id) for f in features):
                        return _json(start_response, "403 Forbidden", {"error": feature_access.explain_denied(session, features[0], user.plan, user.id)})
                    break
        finally:
            session.close()
        return downstream(environ, start_response)

    return application
