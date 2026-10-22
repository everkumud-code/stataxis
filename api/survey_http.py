"""HTTP for polls and surveys.

  * /api/v1/surveys/...           the administrator's routes (build, open, close, read the results, export, invite, remove answers): administrators only;
  * /api/v1/public/survey/<slug>  what a respondent's page needs: the definition, sending an answer, and the public results when the survey allows them;
  * /survey/<slug>, /survey/<slug>/results, /polls   the pages anyone may open.

Sending an answer is limited by address (and per survey), a hidden trap field catches simple bots, and the answers are checked on the server against the survey's own rules; nothing the page sends is trusted.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any, Callable
from urllib.parse import parse_qs

from api import survey_core as core
from api import survey_pages
from api.auth_service import authenticate
from api.errors import AuthenticationError, AuthorizationError
from api.market_http import _json
from api.rate_limit import client_ip, limiter
from collector.storage import Survey, SurveyResponse, User

MAX_BODY = 600_000
MAX_IMAGE_BODY = 3_800_000   # a 2.5 MB picture as base64 inside JSON
_CACHE: dict[tuple[int, str], tuple[float, Any]] = {}


def _read_body(environ: dict[str, Any], limit: int = MAX_BODY) -> dict[str, Any]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError as exc:
        raise ValueError("invalid content length") from exc
    if length <= 0 or length > limit:
        raise ValueError(f"the request body must be between 1 byte and {limit // 1000} KB")
    try:
        payload = json.loads(environ["wsgi.input"].read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("the request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("the request body must be a JSON object")
    return payload


def _int(value: Any, label: str, default: int | None = None) -> int:
    if value in (None, "") and default is not None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc


def _file(start_response: Callable[..., Any], body: bytes, content_type: str, name: str):
    start_response("200 OK", [("Content-Type", content_type), ("Content-Disposition", f'attachment; filename="{name}"'), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
    return [body]


# ----------------------------------------------------------------------------------------------- the administrator
def survey_admin_application(session_factory: Callable[[], Any]):
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
                    raise AuthorizationError("only an administrator can run polls and surveys")
                return _admin(session, user, method, path[len("/api/v1/surveys/"):].strip("/"), q, environ, start_response)
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


def _admin(session: Any, user: User, method: str, route: str, q: dict[str, str], environ: dict[str, Any], start_response: Callable[..., Any]):
    if method == "GET":
        if route in ("", "list"):
            return _json(start_response, 200, {"surveys": core.list_surveys(session), "templates": core.template_list(), "categories": list(core.CATEGORIES), "states": list(core.STATUSES), "base_url": core.sc_base()})
        if route == "template":
            return _json(start_response, 200, {"survey": core.from_template(q.get("key", ""))})
        if route == "demographics":
            return _json(start_response, 200, {"questions": core.demographics()})
        row = core.get_survey(session, _int(q.get("id"), "id"))
        if route == "get":
            return _json(start_response, 200, {"survey": core.serialize(row, session)})
        if route == "results":
            return _json(start_response, 200, core.survey_results(session, row, include_flagged=q.get("flagged", "1") != "0"))
        if route == "crosstab":
            return _json(start_response, 200, core.crosstab(session, row, q.get("target", ""), q.get("by", ""), include_flagged=q.get("flagged", "1") != "0"))
        if route == "responses":
            return _json(start_response, 200, core.list_responses(session, row, page=_int(q.get("page"), "page", 1), status=q.get("status", ""), include_contact=q.get("contact") == "1"))
        if route == "invites":
            return _json(start_response, 200, core.invite_summary(session, row.id))
        if route == "history":
            return _json(start_response, 200, {"revisions": core.revisions(session, row.id)})
        if route == "export":
            kw = {"include_contact": q.get("contact") == "1", "include_flagged": q.get("flagged", "1") != "0"}
            if q.get("format") == "xlsx":
                return _file(start_response, core.export_xlsx(session, row, **kw), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{row.slug}.xlsx")
            return _file(start_response, core.export_csv(session, row, **kw), "text/csv; charset=utf-8", f"{row.slug}.csv")
        return _json(start_response, 404, {"error": "not found"})
    if method != "POST":
        return _json(start_response, 405, {"error": "method not allowed"})
    if route == "images/upload":
        body = _read_body(environ, MAX_IMAGE_BODY)
        try:
            raw = base64.b64decode(str(body.get("data") or "").split(",", 1)[-1], validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("The picture could not be read. Please try another file.") from None
        purpose = str(body.get("purpose") or "option")
        return _json(start_response, 200, core.store_image(session, str(body.get("filename") or "picture"), raw, user.email, purpose if purpose in core.SIZE_LIMITS else "option"))
    body = _read_body(environ)
    if route == "save":
        saved = core.save_survey(session, user.email, body, _int(body["id"], "id") if body.get("id") else None)
        _CACHE.clear()
        _HOME.clear()
        return _json(start_response, 200, {"survey": saved})
    if route == "status":
        saved = core.set_status(session, user.email, _int(body.get("id"), "id"), str(body.get("status") or ""))
        _CACHE.clear()
        _HOME.clear()
        return _json(start_response, 200, {"survey": saved})
    if route == "delete":
        out = core.delete_survey(session, user.email, _int(body.get("id"), "id"))
        _CACHE.clear()
        _HOME.clear()
        return _json(start_response, 200, out)
    if route == "duplicate":
        return _json(start_response, 200, {"survey": core.duplicate_survey(session, user.email, _int(body.get("id"), "id"))})
    if route == "response-status":
        out = core.set_response_status(session, _int(body.get("id"), "id"), str(body.get("status") or ""))
        _CACHE.clear()
        return _json(start_response, 200, out)
    if route == "purge":
        n = core.purge_removed(session, _int(body.get("id"), "id"))
        return _json(start_response, 200, {"purged": n})
    if route == "invites/create":
        row = core.get_survey(session, _int(body.get("id"), "id"))
        if row.access != "invite":
            raise ValueError("this survey is open to everyone; set it to invitation only first")
        made = core.create_invites(session, row, body.get("labels") if isinstance(body.get("labels"), list) else None, _int(body.get("count"), "count", 0))
        base = f"{core.sc_base()}/survey/{row.slug}"
        return _json(start_response, 200, {"links": [{"label": m["label"], "url": f"{base}?i={m['code']}"} for m in made], "message": "Keep these links now. They are shown only once."})
    if route == "preview":
        current = core.get_survey(session, _int(body["id"], "id")) if body.get("id") else None
        data = core.clean_survey({**body, "slug": body.get("slug") or "preview-only"}, session, current)
        probe = Survey(**{k: v for k, v in data.items() if k not in ("questions", "contact_fields")})
        probe.contact_fields, probe.questions_json = data["contact_fields"], json.dumps(data["questions"])
        defn = core.public_definition(probe)
        return _json(start_response, 200, {"html": survey_pages.survey_page(defn, None, indexable=False)})
    return _json(start_response, 404, {"error": "not found"})


# ----------------------------------------------------------------------------------------------- the public API
def survey_public_application(session_factory: Callable[[], Any]):
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        path, method = environ.get("PATH_INFO", ""), environ.get("REQUEST_METHOD", "GET")
        parts = path[len("/api/v1/public/survey/"):].strip("/").split("/")
        slug, action = parts[0], (parts[1] if len(parts) > 1 else "")
        if not slug or len(parts) > 2:
            return _json(start_response, 404, {"error": "not found"})
        try:
            session = session_factory()
            try:
                row = session.query(Survey).filter_by(slug=slug).first()
                if row is None or row.status == "draft":
                    return _json(start_response, 404, {"error": "not found"})
                if method == "GET" and action == "":
                    ok, why = core.accepting(session, row)
                    return _json(start_response, 200, {"survey": core.public_definition(row), "accepting": ok, "message": core.STRINGS[row.language].get(why, "") if why else ""})
                if method == "GET" and action == "results":
                    key = (id(session_factory), slug)
                    hit = _CACHE.get(key)
                    if hit and time.monotonic() - hit[0] < 15:
                        res = hit[1]
                    else:
                        res = core.public_results(row, session)
                        _CACHE[key] = (time.monotonic(), res)
                    if res is None:
                        return _json(start_response, 403, {"error": "the results of this survey are not public"})
                    return _json(start_response, 200, res)
                if method == "POST" and action == "respond":
                    return _respond(session, row, environ, start_response)
                return _json(start_response, 405 if action in ("", "results", "respond") else 404, {"error": "method not allowed" if action in ("", "results", "respond") else "not found"})
            finally:
                session.close()
        except core.AnswerError as exc:
            return _json(start_response, 400, {"error": str(exc), "errors": exc.errors})
        except ValueError as exc:
            return _json(start_response, 400, {"error": str(exc)})

    return application


def _respond(session: Any, row: Survey, environ: dict[str, Any], start_response: Callable[..., Any]):
    ip = client_ip(environ)
    if limiter.check(f"survey-all:{ip}", 120 if row.allow_repeat else 40, 3600) or limiter.check(f"survey:{row.id}:{ip}", 600 if row.allow_repeat else 8, 3600):
        return _json(start_response, 429, {"error": "Too many answers from this connection. Please try again later."})
    body = _read_body(environ, 60_000)
    if str(body.get("hp") or "").strip():   # the hidden field a person never sees: a bot filled it; it is told "ok" and nothing is stored
        return _json(start_response, 200, {"ok": True})
    device = f"{ip}|{environ.get('HTTP_USER_AGENT', '')[:200]}"
    core.submit_response(session, row, body.get("answers"), contact=body.get("contact"), consent=bool(body.get("consent")), token=str(body.get("token") or "")[:100], device=device,
                         started_ms=body.get("started_ms"), invite=str(body.get("invite") or "")[:100])
    _CACHE.clear()
    _HOME.clear()
    return _json(start_response, 200, {"ok": True})


# ----------------------------------------------------------------------------------------------- the pages
def _image_response(session: Any, path: str, environ: dict[str, Any], start_response: Callable[..., Any], extra: list[tuple[str, str]], method: str):
    """A picture of a survey, by its random key. Pictures never change under their key, so browsers and caches may keep them for a year; they are served as images only, in a sandbox."""
    name = path[len("/survey-img/"):]
    key = name[:-5] if name.endswith(".webp") else ""
    image = core.get_image(session, key)
    if image is None:
        body = b"Not found"
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body)))] + extra)
        return [b"" if method == "HEAD" else body]
    etag = '"' + hashlib.sha1(image.data).hexdigest()[:20] + '"'
    headers = [("Content-Type", "image/webp"), ("Cache-Control", "public, max-age=31536000, immutable"), ("ETag", etag), ("Content-Security-Policy", "default-src 'none'; sandbox"), ("X-Content-Type-Options", "nosniff")] + extra
    if environ.get("HTTP_IF_NONE_MATCH") == etag:
        start_response("304 Not Modified", headers)
        return [b""]
    start_response("200 OK", headers + [("Content-Length", str(len(image.data)))])
    return [b"" if method == "HEAD" else bytes(image.data)]


_HOME: dict[int, tuple[float, list[dict[str, Any]]]] = {}


def inject_home_polls(session_factory: Callable[[], Any], body: bytes) -> bytes:
    """The home page with the open polls on it (kept for 20 seconds). Any failure leaves the page exactly as it was."""
    try:
        key = id(session_factory)
        hit = _HOME.get(key)
        if hit and time.monotonic() - hit[0] < 20:
            items = hit[1]
        else:
            session = session_factory()
            try:
                items = core.home_polls(session)
            finally:
                session.close()
            _HOME[key] = (time.monotonic(), items)
        return survey_pages.inject_home(body, items)
    except Exception:
        return body


def _respond_html(start_response: Callable[..., Any], status: int, html: str, extra: list[tuple[str, str]], method: str):
    body = html.encode("utf-8")
    names = {200: "200 OK", 404: "404 Not Found"}
    start_response(names[status], [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body))), ("Cache-Control", "no-cache")] + extra)
    return [b"" if method == "HEAD" else body]


def survey_site_response(session_factory: Callable[[], Any], environ: dict[str, Any], start_response: Callable[..., Any], extra: list[tuple[str, str]]):
    """/polls, /survey/<slug> and /survey/<slug>/results; None when the path is not one of them."""
    path, method = environ.get("PATH_INFO", ""), environ.get("REQUEST_METHOD", "GET")
    if method not in ("GET", "HEAD") or not (path == "/polls" or path.startswith(("/survey/", "/survey-img/"))):
        return None
    session = session_factory()
    try:
        if path.startswith("/survey-img/"):
            return _image_response(session, path, environ, start_response, extra, method)
        if path == "/polls":
            items = [core.serialize(r) for r in session.query(Survey).filter(Survey.listed.is_(True), Survey.access == "public", Survey.status == "live").order_by(Survey.id.desc()).all()]
            return _respond_html(start_response, 200, survey_pages.polls_index([i for i in items if i["state"] == "open"]), extra, method)
        parts = path[len("/survey/"):].strip("/").split("/")
        slug = parts[0]
        row = session.query(Survey).filter_by(slug=slug).first() if slug and len(parts) <= 2 else None
        if row is None or row.status == "draft":
            return _respond_html(start_response, 404, "<!doctype html><title>Not found</title><meta name=robots content=noindex><p>Not found.</p>", extra + [("X-Robots-Tag", "noindex")], method)
        if len(parts) == 2:
            if parts[1] != "results":
                return _respond_html(start_response, 404, "<!doctype html><title>Not found</title><p>Not found.</p>", extra, method)
            return _respond_html(start_response, 200, survey_pages.results_page(row.title, row.slug, core.public_results(row, session), row.language), extra, method)
        ok, why = core.accepting(session, row)
        defn = core.public_definition(row)
        closed = None if ok else core.STRINGS[row.language][why]
        indexable = bool(row.listed and row.access == "public" and core.state_of(row) == "open")
        return _respond_html(start_response, 200, survey_pages.survey_page(defn, closed, indexable=indexable), extra, method)
    finally:
        session.close()
