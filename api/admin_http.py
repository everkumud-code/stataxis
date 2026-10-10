from __future__ import annotations

import json
from typing import Any, Callable

from api.admin import add_channel, add_video, deactivate_channel, remove_video, rename_channel, set_channel_language, set_channel_segment
from api.auth_service import authenticate
from api import audience as audience_mod
from api import feature_access, user_admin
from api.package_config import list_package_slots, update_package_slot
from collector.storage import User


def admin_application(session_factory: Callable[[], Any]):
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "")
        try:
            identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
            if not identity.is_admin:
                raise PermissionError("admin access required")
            if path == "/api/v1/admin/packages" and method == "GET":
                session = session_factory()
                try:
                    return _json(start_response, 200, {"packages": list_package_slots(session)})
                finally:
                    session.close()
            if method != "POST":
                return _json(start_response, 405, {"error": "method not allowed"})
            length = int(environ.get("CONTENT_LENGTH") or "0")
            if length <= 0 or length > 16384:
                raise ValueError("request body must be between 1 and 16384 bytes")
            body = json.loads(environ["wsgi.input"].read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object")
            session = session_factory()
            try:
                if path == "/api/v1/admin/packages/configure":
                    slot = int(body.get("slot"))
                    return _json(start_response, 200, {"package": update_package_slot(session, slot, body)})
                if path == "/api/v1/admin/audience/set":
                    return _json(start_response, 200, audience_mod.set_profile(session, channel_id=int(body.get("channel_id")), source=str(body.get("source") or ""), source_note=str(body.get("source_note") or ""),
                                                                              as_of=str(body.get("as_of") or ""), age=body.get("age"), gender=body.get("gender"), states=body.get("states"),
                                                                              countries=body.get("countries"), by=identity.email))
                if path == "/api/v1/admin/audience/remove":
                    return _json(start_response, 200, audience_mod.remove_profile(session, int(body.get("channel_id"))))
                if path == "/api/v1/admin/features/list":
                    return _json(start_response, 200, {"features": feature_access.matrix(session), "plans": feature_access.plans_overview()})
                if path == "/api/v1/admin/features/set":
                    return _json(start_response, 200, feature_access.set_min_plan(session, str(body.get("feature") or ""), str(body.get("min_plan") or ""), identity.email))
                if path == "/api/v1/admin/users/list":
                    return _json(start_response, 200, {"users": user_admin.list_users(session, q=str(body.get("q") or ""), plan=str(body.get("plan") or ""), status=str(body.get("status") or "")),
                                                       "plans": feature_access.plans_overview()})
                if path == "/api/v1/admin/users/features":
                    target = session.get(User, int(body.get("user_id")))
                    if target is None: raise LookupError("user not found")
                    return _json(start_response, 200, {"user": user_admin.payload(target), "features": feature_access.user_matrix(session, target), "plans": feature_access.plans_overview()})
                if path == "/api/v1/admin/users/features/set":
                    raw = body.get("allowed")
                    if raw is not None and not isinstance(raw, bool): raise ValueError("allowed must be true, false or null")
                    return _json(start_response, 200, {"features": feature_access.set_user_feature(session, int(body.get("user_id")), str(body.get("feature") or ""), raw, identity.email)})
                if path == "/api/v1/admin/users/plan":
                    return _json(start_response, 200, user_admin.set_plan(session, int(body.get("user_id")), str(body.get("plan") or "")))
                if path == "/api/v1/admin/users/active":
                    return _json(start_response, 200, user_admin.set_active(session, int(body.get("user_id")), bool(body.get("active")), identity.user_id))
                if path == "/api/v1/admin/users/create":
                    return _json(start_response, 200, user_admin.create_user(session, email=str(body.get("email") or ""), name=str(body.get("name") or ""), organization=str(body.get("organization") or ""),
                                                                              mobile=str(body.get("mobile") or ""), plan=str(body.get("plan") or "")))
                if path == "/api/v1/admin/users/reset-password":
                    return _json(start_response, 200, user_admin.reset_password(session, int(body.get("user_id"))))
                if path == "/api/v1/admin/users/approve":
                    user_id = int(body.get("user_id")); user = session.query(User).filter_by(id=user_id).one_or_none()
                    if user is None: raise LookupError("user not found")
                    user_admin.check_seat(session, user.organization, user.requested_plan or user.plan, exclude_user_id=user.id)
                    user.approval_status = "approved"; user.active = True
                    if user.requested_plan: user.plan = user.requested_plan
                    session.commit()
                    return _json(start_response, 200, {"approved": True, "user": _user_payload(user)})
                if path == "/api/v1/admin/users/reject":
                    user_id = int(body.get("user_id")); user = session.query(User).filter_by(id=user_id).one_or_none()
                    if user is None: raise LookupError("user not found")
                    user.approval_status = "rejected"; user.active = False; session.commit()
                    return _json(start_response, 200, {"rejected": True, "user_id": user_id})
                if path == "/api/v1/admin/users/pending":
                    users = session.query(User).filter_by(approval_status="pending").order_by(User.created_at.asc()).all()
                    return _json(start_response, 200, {"users": [_user_payload(user) for user in users]})
                if path == "/api/v1/admin/channels":
                    return _json(start_response, 200, add_channel(session, identity, body.get("url", ""), body.get("display_name", ""), body.get("language", ""), body.get("region", ""), body.get("market", ""), segment=body.get("segment") or None))
                if path == "/api/v1/admin/channels/segment":
                    return _json(start_response, 200, set_channel_segment(session, identity, int(body.get("channel_id")), str(body.get("segment") or "")))
                if path == "/api/v1/admin/channels/deactivate":
                    return _json(start_response, 200, deactivate_channel(session, identity, int(body.get("channel_id"))))
                if path == "/api/v1/admin/channels/rename":
                    return _json(start_response, 200, rename_channel(session, identity, int(body.get("channel_id")), body.get("display_name", "")))
                if path == "/api/v1/admin/videos/remove":
                    video_id = int(body.get("video_id")); remove_video(session, identity, video_id)
                    return _json(start_response, 200, {"removed": True, "video_id": video_id})
                if path == "/api/v1/admin/videos":
                    url, name = body.get("url"), body.get("display_name")
                    if not isinstance(url, str) or not url.strip(): raise ValueError("url is required")
                    if not isinstance(name, str) or not name.strip(): raise ValueError("display_name is required")
                    return _json(start_response, 200, add_video(session, identity, url, name))
                if path == "/api/v1/admin/channels/language":
                    channel_id = int(body.get("channel_id")); language = body.get("language")
                    if not isinstance(language, str): raise ValueError("language is required")
                    return _json(start_response, 200, set_channel_language(session, identity, channel_id, language))
                return _json(start_response, 404, {"error": "not found"})
            finally:
                session.close()
        except PermissionError as exc:
            return _json(start_response, 403 if "admin" in str(exc) else 401, {"error": str(exc)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return _json(start_response, 400, {"error": str(exc)})
        except LookupError as exc:
            return _json(start_response, 404, {"error": str(exc)})
    return application


def _user_payload(user: User) -> dict[str, Any]:
    return {"id": user.id, "name": user.full_name, "email": user.email, "mobile": user.mobile,
            "organization": user.organization, "purpose_of_use": user.purpose_of_use,
            "requested_plan": user.requested_plan, "approval_status": user.approval_status,
            "created_at": user.created_at.isoformat() if user.created_at else None}


def _json(start_response: Callable[..., Any], status: int, payload: dict[str, Any]):
    body = json.dumps(payload, default=str).encode("utf-8")
    reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed"}.get(status, "Error")
    start_response(f"{status} {reason}", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]
