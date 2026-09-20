"""HTTP endpoints for authenticated precision live sampling, windows and Excel export."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from api.access import require_capability
from api.auth_service import authenticate, policy_for_identity
from api.errors import AuthenticationError, AuthorizationError
from api.export import export_live_audience_xlsx, export_live_stats_xlsx
from api.live_monitor import live_audience_window, sample_live_url
from api.live_stats import live_snapshot, live_window_stats


def live_application(session_factory: Callable[[], Any]):
    """Expose authenticated precision live sampling, audience windows and Excel export."""
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "GET")

        if path == "/api/v1/audience/live/export":
            if method != "GET":
                return _json(start_response, 405, {"error": "method not allowed"})
            try:
                identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
                require_capability(policy_for_identity(identity), "can_download_report")
                query = _query(environ.get("QUERY_STRING", ""))
                end_at = _parse_datetime(query.get("end")) or datetime.now(UTC)
                start_at = _parse_datetime(query.get("start")) or end_at - timedelta(hours=1)
                session = session_factory()
                try:
                    body = export_live_audience_xlsx(
                        session,
                        start_at=start_at,
                        end_at=end_at,
                        language=query.get("language"),
                    )
                finally:
                    session.close()
                start_response("200 OK", [
                    ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                    ("Content-Disposition", "attachment; filename=stataxis-live-audience.xlsx"),
                    ("Content-Length", str(len(body))),
                ])
                return [body]
            except AuthenticationError as exc:
                return _json(start_response, 401, {"error": str(exc)})
            except AuthorizationError as exc:
                return _json(start_response, 403, {"error": str(exc)})
            except ValueError as exc:
                return _json(start_response, 400, {"error": str(exc)})

        if path == "/api/v1/audience/live":
            if method != "GET":
                return _json(start_response, 405, {"error": "method not allowed"})
            try:
                identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
                require_capability(policy_for_identity(identity), "can_evaluate_url")
                query = _query(environ.get("QUERY_STRING", ""))
                end_at = _parse_datetime(query.get("end")) or datetime.now(UTC)
                start_at = _parse_datetime(query.get("start")) or end_at - timedelta(hours=1)
                session = session_factory()
                try:
                    payload = live_audience_window(session, start_at=start_at, end_at=end_at, language=query.get("language"))
                finally:
                    session.close()
                return _json(start_response, 200, payload)
            except AuthenticationError as exc:
                return _json(start_response, 401, {"error": str(exc)})
            except AuthorizationError as exc:
                return _json(start_response, 403, {"error": str(exc)})
            except ValueError as exc:
                return _json(start_response, 400, {"error": str(exc)})

        if path in {"/api/v1/audience/live/stats", "/api/v1/audience/live/stats/export", "/api/v1/audience/live/snapshot"}:
            if method != "GET":
                return _json(start_response, 405, {"error": "method not allowed"})
            try:
                identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
                is_export = path.endswith("/export")
                require_capability(policy_for_identity(identity), "can_download_report" if is_export else "can_evaluate_url")
                query = _query(environ.get("QUERY_STRING", ""))
                language, segment = query.get("language"), query.get("segment")
                session = session_factory()
                try:
                    if path.endswith("/snapshot"):
                        at = _parse_datetime(query.get("at")) or datetime.now(UTC)
                        return _json(start_response, 200, live_snapshot(session, at=at, language=language, segment=segment))
                    end_at = _parse_datetime(query.get("end")) or datetime.now(UTC)
                    start_at = _parse_datetime(query.get("start")) or end_at - timedelta(hours=1)
                    bucket = int(query.get("bucket_seconds", "60"))
                    if is_export:
                        body = export_live_stats_xlsx(session, start_at=start_at, end_at=end_at, language=language, segment=segment, bucket_seconds=bucket)
                        start_response("200 OK", [
                            ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                            ("Content-Disposition", "attachment; filename=stataxis-live-feed-stats.xlsx"),
                            ("Content-Length", str(len(body))),
                        ])
                        return [body]
                    payload = live_window_stats(session, start_at=start_at, end_at=end_at, language=language, segment=segment, bucket_seconds=bucket)
                finally:
                    session.close()
                return _json(start_response, 200, payload)
            except AuthenticationError as exc:
                return _json(start_response, 401, {"error": str(exc)})
            except AuthorizationError as exc:
                return _json(start_response, 403, {"error": str(exc)})
            except ValueError as exc:
                return _json(start_response, 400, {"error": str(exc)})

        if path == "/api/v1/evaluate/youtube/live-sample":
            if method != "POST":
                return _json(start_response, 405, {"error": "method not allowed"})
            try:
                identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
                payload = _read_json(environ)
                url = payload.get("url")
                display_name = payload.get("display_name")
                if not isinstance(url, str) or not url.strip():
                    raise ValueError("url is required")
                if not isinstance(display_name, str) or not display_name.strip():
                    raise ValueError("display_name is required")
                session = session_factory()
                try:
                    result = sample_live_url(session, identity, url, display_name)
                finally:
                    session.close()
                return _json(start_response, 200, result)
            except AuthenticationError as exc:
                return _json(start_response, 401, {"error": str(exc)})
            except AuthorizationError as exc:
                return _json(start_response, 403, {"error": str(exc)})
            except ValueError as exc:
                return _json(start_response, 400, {"error": str(exc)})
            except RuntimeError as exc:
                return _json(start_response, 500, {"error": str(exc)})

        return _json(start_response, 404, {"error": "not found"})

    return application


def _query(raw: str) -> dict[str, str]:
    from urllib.parse import parse_qs
    return {key: values[0] for key, values in parse_qs(raw).items() if values}


def _parse_datetime(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    raw = value.strip()
    if " " in raw and "T" in raw:
        raw = raw.replace(" ", "+")
    return datetime.fromisoformat(raw)


def _read_json(environ: dict[str, Any]) -> dict[str, Any]:
    try:
        length = int(environ.get("CONTENT_LENGTH", "0"))
    except (TypeError, ValueError):
        raise ValueError("invalid content length")
    if length < 1 or length > 16384:
        raise ValueError("request body must be between 1 and 16384 bytes")
    body = environ["wsgi.input"].read(length)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    return payload


def _json(start_response: Callable[..., Any], status: int, payload: dict[str, Any]):
    reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 500: "Internal Server Error"}[status]
    body = json.dumps(payload).encode("utf-8")
    start_response(f"{status} {reason}", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]
