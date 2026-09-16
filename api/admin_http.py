from __future__ import annotations

import json
from typing import Any, Callable

from api.admin import add_video, remove_video, set_channel_language
from api.auth_service import authenticate


def admin_application(session_factory: Callable[[], Any]):
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        path = environ.get("PATH_INFO", "")
        if environ.get("REQUEST_METHOD") != "POST":
            return _json(start_response, 405, {"error": "method not allowed"})
        try:
            identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
            length = int(environ.get("CONTENT_LENGTH") or "0")
            if length <= 0 or length > 16384:
                raise ValueError("request body must be between 1 and 16384 bytes")
            body = json.loads(environ["wsgi.input"].read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object")
            session = session_factory()
            try:
                if path == "/api/v1/admin/videos/remove":
                    video_id = int(body.get("video_id"))
                    remove_video(session, identity, video_id)
                    return _json(start_response, 200, {"removed": True, "video_id": video_id})
                if path == "/api/v1/admin/videos":
                    url = body.get("url")
                    name = body.get("display_name")
                    if not isinstance(url, str) or not url.strip():
                        raise ValueError("url is required")
                    if not isinstance(name, str) or not name.strip():
                        raise ValueError("display_name is required")
                    return _json(start_response, 200, add_video(session, identity, url, name))
                if path == "/api/v1/admin/channels/language":
                    channel_id = int(body.get("channel_id"))
                    language = body.get("language")
                    if not isinstance(language, str):
                        raise ValueError("language is required")
                    return _json(start_response, 200, set_channel_language(session, identity, channel_id, language))
                return _json(start_response, 404, {"error": "not found"})
            finally:
                session.close()
        except PermissionError as exc:
            return _json(start_response, 403 if "admin" in str(exc) else 401, {"error": str(exc)})
        except (ValueError, TypeError) as exc:
            return _json(start_response, 400, {"error": str(exc)})
        except LookupError as exc:
            return _json(start_response, 404, {"error": str(exc)})
    return application


def _json(start_response: Callable[..., Any], status: int, payload: dict[str, Any]):
    body = json.dumps(payload).encode("utf-8")
    reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed"}.get(status, "Error")
    start_response(f"{status} {reason}", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]
