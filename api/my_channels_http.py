"""HTTP endpoints for a login's own channels (/api/v1/my/channels...). Every signed-in, active account may use them; each account only ever sees and changes its own claims."""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib.parse import parse_qs

from api import my_channels
from api.auth_service import authenticate
from api.errors import AuthenticationError
from api.rate_limit import limiter
from collector.storage import User

_REASONS = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 429: "Too Many Requests", 502: "Bad Gateway"}
HELP = ("Put this code anywhere in your channel's description (YouTube Studio, Customization, Basic info), save it, then press Verify. "
        "Only the person who controls a channel can edit its description, so finding the code proves the channel is yours. You can delete the code afterwards.")
YOUTUBE_DOWN = "YouTube could not be reached just now; try again shortly."
YOUTUBE_MISSING = "YouTube could not find that channel. Check the handle, or pick it from the tracked channels."


def _json(start_response: Callable[..., Any], status: int, payload: dict[str, Any]):
    body = json.dumps(payload, default=str).encode("utf-8")
    start_response(f"{status} {_REASONS.get(status, 'OK')}", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]


def _body(environ: dict[str, Any]) -> dict[str, Any]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError as exc:
        raise ValueError("invalid content length") from exc
    if length <= 0 or length > 8192:
        raise ValueError("request body must be between 1 and 8192 bytes")
    try:
        data = json.loads(environ["wsgi.input"].read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("request body must be valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("request body must be a JSON object")
    return data


def _youtube_failure(start_response: Callable[..., Any], exc: Exception):
    """A YouTube problem is reported plainly, never as a server error with details."""
    missing = "not found" in str(exc).lower()
    return _json(start_response, 502, {"error": YOUTUBE_MISSING if missing else YOUTUBE_DOWN})


def my_channels_application(session_factory: Callable[[], Any]):
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        path, method = environ.get("PATH_INFO", ""), environ.get("REQUEST_METHOD", "GET")
        try:
            identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
            session = session_factory()
            try:
                user = session.get(User, identity.user_id)
                if user is None or not user.active:
                    raise AuthenticationError("authentication required")
                if (method, path) == ("GET", "/api/v1/my/channels"):
                    return _json(start_response, 200, {"claims": my_channels.mine(session, user.id), "channel_ids": my_channels.approved_channel_ids(session, user.id), "help": HELP})
                if (method, path) == ("GET", "/api/v1/my/channels/search"):
                    q = {k: v[0] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items() if v}
                    return _json(start_response, 200, {"channels": my_channels.search_tracked(session, user.id, q.get("q", ""))})
                if method != "POST":
                    return _json(start_response, 405, {"error": "method not allowed"})
                body = _body(environ)
                if path == "/api/v1/my/channels/claim":
                    if body.get("channel_id") not in (None, ""):
                        return _json(start_response, 200, {"claim": my_channels.claim_tracked(session, user, int(body["channel_id"])), "help": HELP})
                    if limiter.check(f"claim-ref:{user.id}", 8, 3600):
                        return _json(start_response, 429, {"error": "too many lookups; try again in a while"})
                    try:
                        return _json(start_response, 200, {"claim": my_channels.claim_by_ref(session, user, str(body.get("ref") or "")), "help": HELP})
                    except (ValueError, LookupError, PermissionError):
                        raise
                    except Exception as exc:
                        return _youtube_failure(start_response, exc)
                if path == "/api/v1/my/channels/verify":
                    if limiter.check(f"claim-verify:{user.id}", 10, 3600):
                        return _json(start_response, 429, {"error": "too many checks; try again in a while"})
                    try:
                        return _json(start_response, 200, my_channels.verify(session, user, int(body.get("claim_id"))))
                    except (ValueError, LookupError, PermissionError):
                        raise
                    except Exception as exc:
                        return _youtube_failure(start_response, exc)
                if path == "/api/v1/my/channels/remove":
                    return _json(start_response, 200, my_channels.remove(session, user, int(body.get("claim_id"))))
                return _json(start_response, 404, {"error": "not found"})
            finally:
                session.close()
        except AuthenticationError as exc:
            return _json(start_response, 401, {"error": str(exc)})
        except PermissionError as exc:
            return _json(start_response, 403, {"error": str(exc)})
        except LookupError as exc:
            return _json(start_response, 404, {"error": str(exc)})
        except (ValueError, TypeError) as exc:
            return _json(start_response, 400, {"error": str(exc)})

    return application
