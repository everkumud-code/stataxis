"""HTTP endpoints for the Facebook, Instagram and X screens, and for the administrator's setup of them.

Reading (rankings, one channel, compare, top posts, presence beside YouTube) is the privilege "social"; the Excel file is "data_export". The setup routes under /api/v1/social/admin/ are for administrators only:
the platform keys (kept on the server, shown as their last four characters), the linked accounts, importing accounts, follower figures and posts from a sheet, and reading an account now.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Callable
from urllib.parse import parse_qs

from api import feature_access, social
from api.auth_service import authenticate
from api.errors import AuthenticationError, AuthorizationError
from api.market_http import _int, _json
from api.social_export import export_social_xlsx
from collector.social import service, settings as social_settings
from collector.social.base import PLATFORM_LABEL
from collector.storage import Channel, SocialAccount, User

READ_ROUTES = {
    "/api/v1/social/overview": "social", "/api/v1/social/presence": "social", "/api/v1/social/channel": "social", "/api/v1/social/compare": "social", "/api/v1/social/posts": "social",
    "/api/v1/social/export.xlsx": "data_export",
}
MAX_BODY = 2_100_000


def _read_body(environ: dict[str, Any]) -> dict[str, Any]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError as exc:
        raise ValueError("invalid content length") from exc
    if length <= 0 or length > MAX_BODY:
        raise ValueError("the request body must be between 1 byte and 2 MB")
    try:
        payload = json.loads(environ["wsgi.input"].read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("the request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("the request body must be a JSON object")
    return payload


def _ids(raw: str | None) -> list[int]:
    out = []
    for part in (raw or "").split(","):
        if part.strip():
            if not part.strip().isdigit():
                raise ValueError("channels must be channel numbers separated by commas")
            out.append(int(part))
    return out


def account_listing(session: Any, *, platform: str | None = None, channel_id: int | None = None, problems_only: bool = False) -> list[dict[str, Any]]:
    query = session.query(SocialAccount, Channel).join(Channel, Channel.id == SocialAccount.channel_id)
    if platform:
        query = query.filter(SocialAccount.platform == platform)
    if channel_id:
        query = query.filter(SocialAccount.channel_id == channel_id)
    out = []
    for a, c in query.order_by(Channel.name, SocialAccount.platform).all():
        if problems_only and (a.last_status in (None, "ok") or not a.active):
            continue
        out.append({"id": a.id, "channel_id": c.id, "channel": c.name, "language": c.language, "platform": a.platform, "platform_label": PLATFORM_LABEL.get(a.platform, a.platform), "handle": a.handle,
                    "display_name": a.display_name, "url": a.url, "active": a.active, "status": a.last_status, "error": a.last_error,
                    "last_checked_at": a.last_checked_at.isoformat() if a.last_checked_at else None, "last_ok_at": a.last_ok_at.isoformat() if a.last_ok_at else None})
    return out


def admin_status(session: Any) -> dict[str, Any]:
    return {**social.coverage(session), "accounts_list": account_listing(session)}


def social_application(session_factory: Callable[[], Any]):
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        path, method = environ.get("PATH_INFO", ""), environ.get("REQUEST_METHOD", "GET")
        q = {k: v[0].strip() for k, v in parse_qs(environ.get("QUERY_STRING", "")).items() if v}
        try:
            identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
            is_admin_route = path.startswith("/api/v1/social/admin/")
            if not is_admin_route and not (method == "GET" and path in READ_ROUTES):
                return _json(start_response, 404, {"error": "not found"})
            session = session_factory()
            try:
                user = session.get(User, identity.user_id)
                if user is None or not user.active:
                    raise AuthenticationError("authentication required")
                if is_admin_route:
                    if not user.is_admin:
                        raise AuthorizationError("only an administrator can set up the social media accounts")
                    return _admin(session, user, method, path, q, environ, start_response)
                feature = READ_ROUTES[path]
                if not feature_access.allowed(session, feature, user.plan, user.is_admin, user.id):
                    raise AuthorizationError(feature_access.explain_denied(session, feature, user.plan, user.id))
                language, segment, platform = q.get("language") or None, q.get("segment") or None, q.get("platform") or None
                days = _int(q.get("days"), "days", 30)
                if path == "/api/v1/social/overview":
                    return _json(start_response, 200, social.overview(session, platform=platform, language=language, segment=segment, days=days, sort=q.get("sort") or "followers"))
                if path == "/api/v1/social/presence":
                    return _json(start_response, 200, social.presence(session, language=language, segment=segment, days=days))
                if path == "/api/v1/social/channel":
                    return _json(start_response, 200, social.channel_social(session, _int(q.get("channel_id"), "channel_id", 0), days=_int(q.get("days"), "days", 90)))
                if path == "/api/v1/social/compare":
                    return _json(start_response, 200, social.compare(session, _ids(q.get("channels")), platform=platform or "", days=_int(q.get("days"), "days", 30)))
                if path == "/api/v1/social/posts":
                    return _json(start_response, 200, social.top_posts(session, platform=platform, language=language, segment=segment, days=_int(q.get("days"), "days", 7), limit=_int(q.get("limit"), "limit", 30), sort=q.get("sort") or "interactions"))
                if path == "/api/v1/social/export.xlsx":
                    body, name = export_social_xlsx(session, platform=platform, language=language, segment=segment, days=days)
                    start_response("200 OK", [("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"), ("Content-Disposition", f'attachment; filename="{name}"'), ("Content-Length", str(len(body)))])
                    return [body]
                return _json(start_response, 404, {"error": "not found"})
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


def _admin(session: Any, user: User, method: str, path: str, q: dict[str, str], environ: dict[str, Any], start_response: Callable[..., Any]):
    route = path[len("/api/v1/social/admin/"):]
    if method == "GET":
        if route == "status":
            return _json(start_response, 200, admin_status(session))
        if route == "accounts":
            return _json(start_response, 200, {"accounts": account_listing(session, platform=q.get("platform") or None, channel_id=_int(q.get("channel_id"), "channel_id", 0) or None, problems_only=q.get("problems") == "1")})
        return _json(start_response, 404, {"error": "not found"})
    if method != "POST":
        return _json(start_response, 405, {"error": "method not allowed"})
    body = _read_body(environ)
    if route == "settings":
        social_settings.save(session, user.email, body)
        return _json(start_response, 200, {"settings": social_settings.public_status(session)})
    if route == "accounts/save":
        row = service.save_account(session, channel_id=int(body.get("channel_id") or 0), platform=str(body.get("platform") or ""), handle=str(body.get("handle") or ""), by=user.email,
                                   active=bool(body.get("active", True)), account_id=int(body["id"]) if body.get("id") else None)
        return _json(start_response, 200, {"account": next(a for a in account_listing(session) if a["id"] == row.id)})
    if route == "accounts/delete":
        return _json(start_response, 200, service.delete_account(session, int(body.get("id") or 0)))
    if route == "accounts/import":
        return _json(start_response, 200, service.import_accounts(session, str(body.get("csv") or ""), user.email))
    if route == "stats/import":
        return _json(start_response, 200, service.import_stats(session, str(body.get("csv") or "")))
    if route == "stats/add":
        return _json(start_response, 200, service.add_manual_stats(session, int(body.get("account_id") or 0), day=str(body.get("date") or ""), followers=body.get("followers"), following=body.get("following"), posts=body.get("posts"), by=user.email))
    if route == "posts/import":
        return _json(start_response, 200, service.import_posts(session, str(body.get("csv") or "")))
    if route == "accounts/check":
        account = session.get(SocialAccount, int(body.get("id") or 0))
        if account is None:
            raise LookupError("that account does not exist")
        result = service.check_account(session, account)
        return _json(start_response, 200, {"result": result, "account": next(a for a in account_listing(session) if a["id"] == account.id)})
    if route == "run":
        return _json(start_response, 200, {"counts": service.collect_social(session, force=bool(body.get("force")), now=datetime.now(UTC), limit=30)})
    return _json(start_response, 404, {"error": "not found"})
