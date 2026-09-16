"""Production WSGI entrypoint for StatAxis dashboard and API."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from api.auth_guard import protect_application
from api.auth_http import auth_application
from api.http import wsgi_application
from collector.storage import create_database

ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / "dashboard"
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("STAXIS_DATABASE_URL") or "sqlite:///stataxis.db"

_engine = create_database(DATABASE_URL)


def _session() -> Session:
    return Session(_engine)


_api = protect_application(wsgi_application(_session))
_auth_api = auth_application(_session)


def application(environ: dict[str, Any], start_response: Callable[..., Any]):
    path = environ.get("PATH_INFO", "/")
    if path.startswith("/api/v1/auth/"):
        return _auth_api(environ, start_response)
    if path.startswith("/api/") or path == "/health":
        return _api(environ, start_response)

    if path == "/":
        path = "/index.html"
    if path.startswith("/") and ".." not in Path(path).parts:
        file_path = DASHBOARD / path.lstrip("/")
        if file_path.is_file():
            body = file_path.read_bytes()
            content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            start_response("200 OK", [("Content-Type", content_type), ("Content-Length", str(len(body)))])
            return [body]

    start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
    return [b"Not found"]
