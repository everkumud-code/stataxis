"""Production WSGI entrypoint for StatAxis dashboard and API."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from api.admin_bootstrap import bootstrap_admin
from api.admin_http import admin_application
from api.auth_guard import protect_application
from api.auth_http import auth_application
from api.evaluate_http import evaluate_application
from api.http import wsgi_application
from api.insight_extensions import insight_application
from api.live_http import live_application
from collector.storage import create_database

ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / "dashboard"
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("STAXIS_DATABASE_URL") or "sqlite:///stataxis.db"

_engine = create_database(DATABASE_URL)


def _session() -> Session:
    return Session(_engine)


with _session() as _bootstrap_session:
    bootstrap_admin(_bootstrap_session)


_api = protect_application(wsgi_application(_session))
_auth_api = auth_application(_session)
_evaluate_api = evaluate_application(_session)
_live_api = live_application(_session)
_admin_api = admin_application(_session)
_insight_api = protect_application(insight_application(_session))


def application(environ: dict[str, Any], start_response: Callable[..., Any]):
    path = environ.get("PATH_INFO", "/")
    if path.startswith("/api/v1/auth/"):
        return _auth_api(environ, start_response)
    if path in {"/api/v1/evaluate/youtube/live-sample", "/api/v1/audience/live", "/api/v1/audience/live/export"}:
        return _live_api(environ, start_response)
    if path.startswith("/api/v1/evaluate/youtube"):
        return _evaluate_api(environ, start_response)
    if path.startswith("/api/v1/admin/"):
        return _admin_api(environ, start_response)
    if path.startswith("/api/v1/insights/"):
        return _insight_api(environ, start_response)
    if path.startswith("/api/") or path == "/health":
        return _api(environ, start_response)

    if path == "/":
        path = "/index.html"
    elif path == "/admin":
        path = "/admin.html"
    elif path == "/login":
        path = "/login.html"
    elif path == "/apply":
        path = "/apply.html"
    elif path == "/workspace":
        path = "/workspace.html"
    if path.startswith("/") and ".." not in Path(path).parts:
        file_path = DASHBOARD / path.lstrip("/")
        if file_path.is_file():
            body = file_path.read_bytes()
            if path == "/index.html":
                marker = b'<a href="#method">Methodology</a>'
                nav = (b'<a href="#method">Methodology</a>'
                       b'<a href="/stax9.html">STAX9 + STX</a>'
                       b'<a href="/stx-index.html">STX Index</a>'
                       b'<a href="/plans.html">SX Packages</a>')
                if marker in body:
                    body = body.replace(marker, nav, 1)
            content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            start_response("200 OK", [("Content-Type", content_type), ("Content-Length", str(len(body)))])
            return [body]

    start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
    return [b"Not found"]