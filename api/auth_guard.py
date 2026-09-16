"""Production authentication boundary for protected StatAxis HTTP routes."""

from __future__ import annotations

from typing import Any, Callable

from api.auth_service import authenticate


def protect_application(downstream: Callable[..., Any]):
    """Require a signed bearer token for commercial/admin API endpoints."""
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        path = environ.get("PATH_INFO", "")
        protected = path == "/api/v1/reports/export" or path.startswith("/api/v1/evaluate") or path.startswith("/api/v1/admin")
        if not protected:
            return downstream(environ, start_response)
        try:
            identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
        except (PermissionError, ValueError):
            return _json(start_response, 401, {"error": "authentication required"})
        environ = dict(environ)
        environ["STATAXIS_USER_ID"] = str(identity.user_id)
        environ["STATAXIS_PLAN"] = identity.plan
        environ["HTTP_X_STATAXIS_ROLE"] = "admin" if identity.is_admin else ("free" if identity.plan == "sx_free" else "paid")
        return downstream(environ, start_response)
    return application


def _json(start_response: Callable[..., Any], status: int, payload: dict[str, Any]):
    import json
    body = json.dumps(payload).encode("utf-8")
    start_response(f"{status} Unauthorized", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]
