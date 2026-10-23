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

from api import feature_access
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


# ----------------------------------------------------------------------------------------------- the people who run polls
CAPS = {"export": "survey_export", "invites": "survey_invites", "pictures": "survey_pictures", "contact": "survey_contact", "public_results": "survey_public_results", "political": "survey_political",
        "publish": "survey_publish"}
DENIED = {"pictures": "Pictures and logos are not switched on for your account. Ask your admin to tick it.", "export": "Downloading answers is not switched on for your account. Ask your admin to tick it.",
          "invites": "Invitation links are not switched on for your account. Ask your admin to tick it.", "contact": "Asking people for personal details is not switched on for your account. Ask your admin to tick it.",
          "public_results": "Showing results to others is not switched on for your account. Ask your admin to tick it.", "political": "Political polls are not switched on for your account. Ask your admin to tick it."}


def caps_of(session: Any, user: User) -> dict[str, bool]:
    """What this person may do with polls and surveys: an administrator everything, anyone else only what an administrator ticked for them."""
    return {name: bool(user.is_admin or feature_access.allowed(session, feature, user.plan, user.is_admin, user.id)) for name, feature in CAPS.items()}


def survey_admin_application(session_factory: Callable[[], Any]):
    """The routes of the Polls and surveys screen. An administrator sees and changes every survey; a client with the "Polls and surveys" tick sees and changes only its own, and only does what its other ticks allow."""
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
                if not feature_access.allowed(session, "surveys", user.plan, user.is_admin, user.id):
                    raise AuthorizationError(feature_access.explain_denied(session, "surveys", user.plan, user.id))
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
    admin, caps = bool(user.is_admin), caps_of(session, user)

    def mine(survey_id: Any) -> Survey:
        row = core.get_survey(session, survey_id)
        if not admin and row.owner_id != user.id:
            raise LookupError("that survey does not exist")   # somebody else's: it is not even said to exist
        return row

    def need(name: str) -> None:
        if not caps[name]:
            raise PermissionError(DENIED[name])

    def restrict(body: dict[str, Any], existing: Survey | None) -> dict[str, Any]:
        """What this person may set. The home page and the public Polls page are the administrators' to give; the rest follow the person's ticks."""
        out = dict(body)
        if not admin:
            out["promote"], out["listed"] = False, False
        if (out.get("category") or (existing.category if existing else "opinion")) == "political":
            need("political")
        if (out.get("contact_mode") if "contact_mode" in out else (existing.contact_mode if existing else "none")) not in (None, "", "none"):
            need("contact")
        if (out.get("results_mode") if "results_mode" in out else (existing.results_mode if existing else "private")) not in (None, "", "private"):
            need("public_results")
        return out

    if method == "GET":
        if route in ("", "list"):
            surveys = core.list_surveys(session, None if admin else user.id)
            if admin:
                owners = {u.id: u.email for u in session.query(User).filter(User.id.in_({s["owner_id"] for s in surveys if s["owner_id"]})).all()} if surveys else {}
                for s in surveys:
                    s["owner"] = owners.get(s["owner_id"], "StatAxis" if not s["owner_id"] else "")
            templates = [t for t in core.template_list() if caps["political"] or t["category"] != "political"]
            return _json(start_response, 200, {"surveys": surveys, "templates": templates, "categories": [c for c in core.CATEGORIES if caps["political"] or c != "political"], "states": list(core.STATUSES),
                                               "base_url": core.sc_base(), "can": caps, "is_admin": admin})
        if route == "template":
            draft = core.from_template(q.get("key", ""))
            if draft.get("category") == "political":
                need("political")
            if not caps["public_results"]:
                draft["results_mode"] = "private"   # a starter must save cleanly for a person who may not show results to others
            return _json(start_response, 200, {"survey": draft})
        if route == "demographics":
            return _json(start_response, 200, {"questions": core.demographics()})
        row = mine(_int(q.get("id"), "id"))
        if route == "get":
            return _json(start_response, 200, {"survey": core.serialize(row, session)})
        if route == "results":
            return _json(start_response, 200, core.survey_results(session, row, include_flagged=q.get("flagged", "1") != "0"))
        if route == "crosstab":
            return _json(start_response, 200, core.crosstab(session, row, q.get("target", ""), q.get("by", ""), include_flagged=q.get("flagged", "1") != "0"))
        if route == "responses":
            return _json(start_response, 200, core.list_responses(session, row, page=_int(q.get("page"), "page", 1), size=_int(q.get("size"), "size", 50), status=q.get("status", ""), include_contact=q.get("contact") == "1" and caps["contact"]))
        if route == "invites":
            return _json(start_response, 200, core.invite_summary(session, row.id))
        if route == "history":
            return _json(start_response, 200, {"revisions": core.revisions(session, row.id)})
        if route == "export":
            need("export")
            kw = {"include_contact": q.get("contact") == "1" and caps["contact"], "include_flagged": q.get("flagged", "1") != "0"}
            if q.get("format") == "xlsx":
                return _file(start_response, core.export_xlsx(session, row, **kw), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{row.slug}.xlsx")
            return _file(start_response, core.export_csv(session, row, **kw), "text/csv; charset=utf-8", f"{row.slug}.csv")
        return _json(start_response, 404, {"error": "not found"})
    if method != "POST":
        return _json(start_response, 405, {"error": "method not allowed"})
    if route == "images/upload":
        need("pictures")
        body = _read_body(environ, MAX_IMAGE_BODY)
        try:
            raw = base64.b64decode(str(body.get("data") or "").split(",", 1)[-1], validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("The picture could not be read. Please try another file.") from None
        purpose = str(body.get("purpose") or "option")
        return _json(start_response, 200, core.store_image(session, str(body.get("filename") or "picture"), raw, user.email, purpose if purpose in core.SIZE_LIMITS else "option"))
    body = _read_body(environ)
    if route == "save":
        existing = mine(_int(body["id"], "id")) if body.get("id") else None
        saved = core.save_survey(session, user.email, restrict(body, existing), existing.id if existing else None, owner_id=user.id, can_publish=admin or caps["publish"], image_owner=None if admin else user.email)
        _CACHE.clear()
        _HOME.clear()
        return _json(start_response, 200, {"survey": saved})
    if route == "status":
        row = mine(_int(body.get("id"), "id"))
        saved = core.set_status(session, user.email, row.id, str(body.get("status") or ""), can_publish=admin or caps["publish"])
        _CACHE.clear()
        _HOME.clear()
        return _json(start_response, 200, {"survey": saved})
    if route == "review/reject":
        if not admin:
            raise PermissionError("only an administrator can send a poll back")
        saved = core.reject_review(session, user.email, _int(body.get("id"), "id"), str(body.get("note") or ""))
        return _json(start_response, 200, {"survey": saved})
    if route == "delete":
        out = core.delete_survey(session, user.email, mine(_int(body.get("id"), "id")).id)
        _CACHE.clear()
        _HOME.clear()
        return _json(start_response, 200, out)
    if route == "duplicate":
        return _json(start_response, 200, {"survey": core.duplicate_survey(session, user.email, mine(_int(body.get("id"), "id")).id, owner_id=user.id)})
    if route == "response-status":
        resp = session.get(SurveyResponse, _int(body.get("id"), "id"))
        if resp is None:
            raise LookupError("that answer does not exist")
        mine(resp.survey_id)
        out = core.set_response_status(session, resp.id, str(body.get("status") or ""))
        _CACHE.clear()
        return _json(start_response, 200, out)
    if route == "purge":
        return _json(start_response, 200, {"purged": core.purge_removed(session, mine(_int(body.get("id"), "id")).id)})
    if route == "invites/create":
        need("invites")
        row = mine(_int(body.get("id"), "id"))
        if row.access != "invite":
            raise ValueError("this survey is open to everyone; set it to invitation only first")
        made = core.create_invites(session, row, body.get("labels") if isinstance(body.get("labels"), list) else None, _int(body.get("count"), "count", 0))
        base = f"{core.sc_base()}/survey/{row.slug}"
        return _json(start_response, 200, {"links": [{"label": m["label"], "url": f"{base}?i={m['code']}"} for m in made], "message": "Keep these links now. They are shown only once."})
    if route == "preview":
        current = mine(_int(body["id"], "id")) if body.get("id") else None
        data = core.clean_survey({**restrict(body, current), "slug": body.get("slug") or "preview-only"}, session, current)
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
                if row is None or row.status in ("draft", "review"):
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
        if row is None or row.status in ("draft", "review"):
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
