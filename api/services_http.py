"""HTTP for the Services section: the administrator's editing routes under /api/v1/cms/, and the public pages (/services, /services/<address>, /sitemap.xml, /robots.txt, /llms.txt).

The editing routes are for administrators only. The public pages need no sign-in; they are written by the server so that a search engine reads plain HTML, and they answer conditional requests (ETag) and
the right codes for an address that moved (301), was removed (410) or never existed (404).
"""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib.parse import parse_qs

from api import blog_cms, services_cms
from api.auth_service import authenticate
from api.errors import AuthenticationError, AuthorizationError
from api.market_http import _json
from collector.storage import User

MAX_BODY = 400_000


def _read_body(environ: dict[str, Any]) -> dict[str, Any]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError as exc:
        raise ValueError("invalid content length") from exc
    if length <= 0 or length > MAX_BODY:
        raise ValueError("the request body must be between 1 byte and 400 KB")
    try:
        payload = json.loads(environ["wsgi.input"].read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("the request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("the request body must be a JSON object")
    return payload


def _int(value: Any, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc


def cms_application(session_factory: Callable[[], Any]):
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        path, method = environ.get("PATH_INFO", ""), environ.get("REQUEST_METHOD", "GET")
        q = {k: v[0].strip() for k, v in parse_qs(environ.get("QUERY_STRING", "")).items() if v}
        try:
            identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
            session = session_factory()
            try:
                user = session.get(User, identity.user_id)
                if user is None or not user.active:
                    raise AuthenticationError("authentication required")
                if not user.is_admin:
                    raise AuthorizationError("only an administrator can edit the website")
                services_cms.ensure_seed(session)
                return _route(session, user, method, path[len("/api/v1/cms/"):], q, environ, start_response)
            finally:
                session.close()
        except AuthenticationError as exc:
            return _json(start_response, 401, {"error": str(exc)})
        except (AuthorizationError, PermissionError) as exc:
            return _json(start_response, 403, {"error": str(exc)})
        except LookupError as exc:
            return _json(start_response, 404, {"error": str(exc)})
        except (ValueError, TypeError) as exc:
            return _json(start_response, 400, {"error": str(exc)})

    return application


def _overview(session: Any) -> dict[str, Any]:
    services = services_cms.list_services(session)
    for s in services:
        s["seo_problems"] = sum(1 for c in services_cms.seo_report(s, services) if c["level"] == "bad")
        s["seo_warnings"] = sum(1 for c in services_cms.seo_report(s, services) if c["level"] == "warn")
    return {"services": services, "page": services_cms.page_settings(session), "base_url": services_cms.BASE_URL, "deleted": services_cms.deleted_revisions(session)}


def _route(session: Any, user: User, method: str, route: str, q: dict[str, str], environ: dict[str, Any], start_response: Callable[..., Any]):
    if method == "GET":
        if route == "services":
            return _json(start_response, 200, _overview(session))
        if route == "services/get":
            s = services_cms.serialize(services_cms.get_service(session, _int(q.get("id"), "id")))
            return _json(start_response, 200, {"service": s, "checks": services_cms.seo_report(s, services_cms.list_services(session))})
        if route == "services/history":
            return _json(start_response, 200, {"revisions": services_cms.revisions(session, _int(q.get("id"), "id"))})
        if route == "posts":
            posts = blog_cms.list_posts(session)
            return _json(start_response, 200, {"posts": posts, "builtin": blog_cms.builtin_posts(), "deleted": blog_cms.deleted_revisions(session), "base_url": services_cms.BASE_URL,
                                               "categories": sorted({p["category"] for p in posts if p["category"]} | set(blog_cms.CATEGORY_SUGGESTIONS))})
        if route == "posts/get":
            p = blog_cms.serialize(blog_cms.get_post(session, _int(q.get("id"), "id")))
            return _json(start_response, 200, {"post": p, "checks": blog_cms.seo_report(p, blog_cms.list_posts(session))})
        if route == "posts/history":
            return _json(start_response, 200, {"revisions": blog_cms.revisions(session, _int(q.get("id"), "id"))})
        if route == "services/version":
            return _json(start_response, 200, services_cms.revision_detail(session, _int(q.get("id"), "id")))
        return _json(start_response, 404, {"error": "not found"})
    if method != "POST":
        return _json(start_response, 405, {"error": "method not allowed"})
    body = _read_body(environ)
    if route == "services/save":
        saved = services_cms.save_service(session, user.email, body, _int(body["id"], "id") if body.get("id") else None)
        return _json(start_response, 200, {"service": saved, "checks": services_cms.seo_report(saved, services_cms.list_services(session))})
    if route == "services/status":
        return _json(start_response, 200, {"service": services_cms.set_status(session, user.email, _int(body.get("id"), "id"), str(body.get("status") or ""))})
    if route == "services/delete":
        return _json(start_response, 200, services_cms.delete_service(session, user.email, _int(body.get("id"), "id")))
    if route == "services/order":
        return _json(start_response, 200, {"services": services_cms.reorder(session, user.email, body.get("ids") if isinstance(body.get("ids"), list) else [])})
    if route == "services/page":
        return _json(start_response, 200, {"page": services_cms.save_page_settings(session, user.email, body)})
    if route == "services/restore":
        return _json(start_response, 200, {"service": services_cms.restore(session, user.email, _int(body.get("revision_id"), "revision_id"))})
    if route == "services/starters":
        return _json(start_response, 200, services_cms.restore_starters(session, user.email))
    if route == "posts/save":
        saved = blog_cms.save_post(session, user.email, body, _int(body["id"], "id") if body.get("id") else None)
        return _json(start_response, 200, {"post": saved, "checks": blog_cms.seo_report(saved, blog_cms.list_posts(session))})
    if route == "posts/status":
        return _json(start_response, 200, {"post": blog_cms.set_status(session, user.email, _int(body.get("id"), "id"), str(body.get("status") or ""), body.get("publish_at"))})
    if route == "posts/delete":
        return _json(start_response, 200, blog_cms.delete_post(session, user.email, _int(body.get("id"), "id")))
    if route == "posts/restore":
        return _json(start_response, 200, {"post": blog_cms.restore(session, user.email, _int(body.get("revision_id"), "revision_id"))})
    if route == "posts/preview":
        current = blog_cms.get_post(session, _int(body["id"], "id")) if body.get("id") else None
        now = services_cms._now().isoformat()
        data = blog_cms.clean(body, session, current)
        data = {**data, "id": current.id if current else None, "live": False, "status": "draft", "published_at": (current.published_at.isoformat() if current and current.published_at else now), "updated_at": now}
        live = [p for p in blog_cms.live_posts(session) if p["slug"] != data["slug"]]
        return _json(start_response, 200, {"html": blog_cms.render_post(data, live, preview=True), "checks": blog_cms.seo_report(data, blog_cms.list_posts(session))})
    if route == "services/preview":
        # the page as it would look and read, from what is on the screen now (nothing is saved); the editor needs no address to check
        current = services_cms.get_service(session, _int(body["id"], "id")) if body.get("id") else None
        data = services_cms.clean(body, session, current)
        data = {**data, "id": current.id if current else None, "status": str(body.get("status") or "draft")}
        published = [s for s in services_cms.list_services(session, published_only=True) if s["slug"] != data["slug"]]
        return _json(start_response, 200, {"html": services_cms.render_service(data, published + [data], preview=True), "checks": services_cms.seo_report(data, services_cms.list_services(session))})
    return _json(start_response, 404, {"error": "not found"})


def site_response(session_factory: Callable[[], Any], environ: dict[str, Any], start_response: Callable[..., Any], extra_headers: list[tuple[str, str]]):
    """The public pages of this section, or None when the path is not one of them (the caller then carries on with the static files)."""
    path, method = environ.get("PATH_INFO", ""), environ.get("REQUEST_METHOD", "GET")
    blog = path.startswith("/blog/")
    if method not in {"GET", "HEAD"} or not (blog or path in {"/services", "/sitemap.xml", "/robots.txt", "/llms.txt"} or path.startswith("/services/")):
        return None
    if path == "/robots.txt":   # needs no database, so it answers even when the database does not
        answer = (200, "text/plain; charset=utf-8", services_cms.robots_txt().encode("utf-8"), '"robots"', None)
    else:
        session = session_factory()
        try:
            if blog:
                answer = blog_cms.respond(session, id(session_factory), path)   # None for the built-in articles and for addresses that are nothing
            else:
                services_cms.ensure_seed(session)
                answer = services_cms.respond(session, id(session_factory), path)
        finally:
            session.close()
    if answer is None:
        return None
    status, ctype, body, etag, location = answer
    if location:
        start_response("301 Moved Permanently", [("Location", location), ("Content-Length", "0")] + extra_headers)
        return [b""]
    names = {200: "200 OK", 404: "404 Not Found", 410: "410 Gone"}
    headers = [("Content-Type", ctype), ("Cache-Control", "public, max-age=0, must-revalidate")] + extra_headers
    if status == 200:
        headers.append(("ETag", etag))
        if environ.get("HTTP_IF_NONE_MATCH") == etag:
            start_response("304 Not Modified", [h for h in headers if h[0] != "Content-Type"])
            return [b""]
    if path.startswith(("/services/", "/blog/")) and status in (404, 410):
        headers.append(("X-Robots-Tag", "noindex"))
    headers.append(("Content-Length", str(len(body))))
    start_response(names[status], headers)
    return [b"" if method == "HEAD" else body]
