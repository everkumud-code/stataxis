"""Production WSGI entrypoint for StatAxis dashboard and API."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from api.admin_bootstrap import bootstrap_admin
from api.admin_http import admin_application
from api.demo_site import DemoSite, demo_page
from api.gate import gate_application
from api.me_http import me_application
from api.auth_guard import protect_application
from api.auth_http import auth_application
from api.evaluate_http import evaluate_application
from api.http import wsgi_application
from api.insight_extensions import insight_application
from api.live_http import live_application
from api.lab_http import lab_application
from api.market_http import market_application
from api.my_channels_http import my_channels_application
from api.public_http import public_application
from collector.storage import create_database

ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / "dashboard"

mimetypes.add_type("image/webp", ".webp")  # older Python builds do not know it
STATIC_EXTENSIONS = frozenset({".html", ".css", ".js", ".svg", ".png", ".jpg", ".webp", ".ico", ".csv", ".json", ".txt", ".woff2"})
SECURITY_HEADERS = (
    ("Strict-Transport-Security", "max-age=31536000"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("X-Frame-Options", "DENY"),
    ("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://*.ytimg.com https://*.ggpht.com https://*.googleusercontent.com; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-site"),
    ("X-Permitted-Cross-Domain-Policies", "none"),
)


def database_url_from_env(environ: dict[str, str] | None = None) -> str:
    values = os.environ if environ is None else environ
    database_url = values.get("DATABASE_URL", "").strip()
    if database_url:
        return database_url
    fallback = values.get("STAXIS_DATABASE_URL", "").strip()
    if fallback:
        return fallback
    return "sqlite:///stataxis.db"


DATABASE_URL = database_url_from_env()
_engine = create_database(DATABASE_URL)


def _session() -> Session:
    return Session(_engine)


with _session() as _bootstrap_session:
    bootstrap_admin(_bootstrap_session)

def _make_routes(session_factory: Callable[[], Session]) -> dict[str, Callable[..., Any]]:
    """Every API of the product, bound to one database. The real site and the demo each get their own set."""
    def gated(app: Callable[..., Any]) -> Callable[..., Any]:
        return gate_application(session_factory, app)

    return {
        "api": gated(protect_application(wsgi_application(session_factory))), "auth": auth_application(session_factory), "evaluate": gated(evaluate_application(session_factory)),
        "live": gated(live_application(session_factory)), "admin": gated(admin_application(session_factory)), "insight": gated(protect_application(insight_application(session_factory))),
        "market": gated(market_application(session_factory)), "my": gated(my_channels_application(session_factory)), "public": public_application(session_factory),
        "me": gated(me_application(session_factory)), "lab": gated(lab_application(session_factory)),
    }


_routes = _make_routes(_session)


def _start_response(start_response: Callable[..., Any], status: str, headers: list[tuple[str, str]], *,
                    no_store: bool = False):
    security = list(SECURITY_HEADERS)
    if no_store:
        security.append(("Cache-Control", "no-store"))
    start_response(status, headers + security)


def _dispatch_api(routes: dict[str, Callable[..., Any]], environ: dict[str, Any], start_response: Callable[..., Any]):
    """Send an /api/ request to the API that owns it; None when the path is not an API path."""
    path = environ.get("PATH_INFO", "")
    if path.startswith("/api/v1/auth/"):
        return routes["auth"](environ, lambda status, headers, *args: _start_response(start_response, status, headers, no_store=True))
    if path in {"/api/v1/evaluate/youtube/live-sample", "/api/v1/audience/live", "/api/v1/audience/live/export", "/api/v1/audience/live/stats", "/api/v1/audience/live/stats/export", "/api/v1/audience/live/snapshot"}:
        return routes["live"](environ, lambda status, headers, *args: _start_response(start_response, status, headers, no_store=True))
    if path.startswith("/api/v1/evaluate/youtube"):
        return routes["evaluate"](environ, lambda status, headers, *args: _start_response(start_response, status, headers, no_store=True))
    if path.startswith("/api/v1/admin/"):
        return routes["admin"](environ, lambda status, headers, *args: _start_response(start_response, status, headers, no_store=True))
    if path.startswith("/api/v1/public/"):
        return routes["public"](environ, lambda status, headers, *args: _start_response(start_response, status, headers))
    if path == "/api/v1/me" or path.startswith("/api/v1/me/"):
        return routes["me"](environ, lambda status, headers, *args: _start_response(start_response, status, headers, no_store=True))
    if path.startswith("/api/v1/lab/"):
        return routes["lab"](environ, lambda status, headers, *args: _start_response(start_response, status, headers, no_store=True))
    if path.startswith("/api/v1/my/"):
        return routes["my"](environ, lambda status, headers, *args: _start_response(start_response, status, headers, no_store=True))
    if path.startswith("/api/v1/market/"):
        return routes["market"](environ, lambda status, headers, *args: _start_response(start_response, status, headers, no_store=True))
    if path.startswith("/api/v1/insights/"):
        return routes["insight"](environ, lambda status, headers, *args: _start_response(start_response, status, headers, no_store=True))
    if path.startswith("/api/") or path == "/health":
        return routes["api"](environ, lambda status, headers, *args: _start_response(start_response, status, headers, no_store=True))
    return None


def _demo_dispatch(session_factory: Callable[[], Session]) -> Callable[..., Any]:
    routes = _make_routes(session_factory)   # built once for each rebuild of the demo data, not for each request
    return lambda environ, start_response: _dispatch_api(routes, environ, start_response)


_demo = DemoSite(_demo_dispatch)


def application(environ: dict[str, Any], start_response: Callable[..., Any]):
    path = environ.get("PATH_INFO", "")
    api_result = _dispatch_api(_routes, environ, start_response)
    if api_result is not None:
        return api_result
    if path.startswith("/demo-api/"):
        return _demo.application(environ, lambda status, headers, *args: _start_response(start_response, status, headers, no_store=True))
    method = environ.get("REQUEST_METHOD", "GET")
    # clean addresses: the old /name.html moves, for good, to /name (the page itself is served at /name)
    if method in {"GET", "HEAD"} and path.endswith(".html") and ".." not in Path(path).parts and ((DASHBOARD / path.lstrip("/")).is_file() or path == "/demo.html"):
        clean = path[:-5]
        if clean.endswith("/index"):
            clean = clean[:-5] or "/"
        query = environ.get("QUERY_STRING", "")
        _start_response(start_response, "301 Moved Permanently", [("Location", (clean or "/") + ("?" + query if query else "")), ("Content-Length", "0")])
        return [b""]
    if path == "/demo":
        body = demo_page((DASHBOARD / "workspace.html").read_text(encoding="utf-8"))
        _start_response(start_response, "200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body)))], no_store=True)
        return [body]

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
    elif path == "/favicon.ico":
        path = "/favicon.svg"
    elif ".." not in Path(path).parts and "." not in path.rsplit("/", 1)[-1] and (DASHBOARD / (path.lstrip("/") + ".html")).is_file():
        path += ".html"   # /platform and /blog/average-beats-peak are the pages platform.html and blog/average-beats-peak.html

    if path.startswith("/") and ".." not in Path(path).parts:
        file_path = DASHBOARD / path.lstrip("/")
        if file_path.suffix.lower() in STATIC_EXTENSIONS and file_path.is_file():
            body = file_path.read_bytes()
            if path == "/index.html":
                marker = b'<a href="#method">Methodology</a>'
                nav = (b'<a href="#method">Methodology</a>'
                       b'<a href="/stax9">STAX9 + STX</a>'
                       b'<a href="/stx-index">STX Index</a>'
                       b'<a href="/plans">SX Packages</a>')
                if marker in body:
                    body = body.replace(marker, nav, 1)
            content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            fresh = [("Cache-Control", "no-cache")] if file_path.suffix.lower() in {".js", ".html", ".css", ".svg"} else []   # pages, scripts and styles are checked again every time, so a release is seen at once
            _start_response(start_response, "200 OK", [("Content-Type", content_type), ("Content-Length", str(len(body)))] + fresh)
            return [body]

    _start_response(start_response, "404 Not Found", [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", "9")])
    return [b"Not found"]
