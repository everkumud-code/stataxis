"""HTTP endpoints for the newer analysis screens: spikes and audience movement, prime-time forecasts and their track record, daily and weekly notes, alerts, and data completeness.

Every route is a privilege of its own (api/feature_access.py), read from the account on each request like the other tools.
"""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import parse_qs

from api import alerts, feature_access, forecasts, notes, report_subscriptions, spikes
from api.auth_service import authenticate
from api.completeness import channel_day_completeness
from api.errors import AuthenticationError, AuthorizationError
from api.market_http import _int, _json, _read_json
from collector.storage import User

ROUTE_FEATURE = {
    ("GET", "/api/v1/lab/spikes"): "spikes",
    ("GET", "/api/v1/lab/movement"): "spikes",
    ("GET", "/api/v1/lab/forecasts"): "forecasts",
    ("GET", "/api/v1/lab/notes"): "notes",
    ("POST", "/api/v1/lab/alerts/list"): "alerts",
    ("POST", "/api/v1/lab/alerts/create"): "alerts",
    ("POST", "/api/v1/lab/alerts/delete"): "alerts",
    ("POST", "/api/v1/lab/alerts/toggle"): "alerts",
    ("POST", "/api/v1/lab/alerts/seen"): "alerts",
    ("GET", "/api/v1/lab/completeness"): "integrity",
    ("GET", "/api/v1/lab/report-subscriptions"): "report_email",
    ("POST", "/api/v1/lab/report-subscriptions/save"): "report_email",
    ("POST", "/api/v1/lab/report-subscriptions/toggle"): "report_email",
    ("POST", "/api/v1/lab/report-subscriptions/delete"): "report_email",
    ("POST", "/api/v1/lab/report-subscriptions/send-now"): "report_email",
}


def lab_application(session_factory: Callable[[], Any]):
    def application(environ: dict[str, Any], start_response: Callable[..., Any]):
        path, method = environ.get("PATH_INFO", ""), environ.get("REQUEST_METHOD", "GET")
        q = {k: v[0].strip() for k, v in parse_qs(environ.get("QUERY_STRING", "")).items() if v}
        try:
            identity = authenticate(environ.get("HTTP_AUTHORIZATION"))
            if (method, path) not in ROUTE_FEATURE:
                return _json(start_response, 404, {"error": "not found"})
            session = session_factory()
            try:
                user = session.get(User, identity.user_id)
                if user is None or not user.active:
                    raise AuthenticationError("authentication required")
                feature = ROUTE_FEATURE[(method, path)]
                allowed = feature_access.allowed(session, feature, user.plan, user.is_admin, user.id)
                if feature == "integrity":   # the completeness table is a system-health view: operations or integrity opens it
                    allowed = allowed or feature_access.allowed(session, "operations", user.plan, user.is_admin, user.id)
                if not allowed:
                    raise AuthorizationError(feature_access.explain_denied(session, feature, user.plan, user.id))
                language, segment = q.get("language") or None, q.get("segment") or None
                if path == "/api/v1/lab/spikes":
                    return _json(start_response, 200, spikes.spikes(session, hours=_int(q.get("hours"), "hours", 6), language=language, segment=segment))
                if path == "/api/v1/lab/movement":
                    return _json(start_response, 200, spikes.movement(session, minutes=_int(q.get("minutes"), "minutes", 30), language=language, segment=segment))
                if path == "/api/v1/lab/forecasts":
                    return _json(start_response, 200, forecasts.forecast_overview(session))
                if path == "/api/v1/lab/notes":
                    return _json(start_response, 200, {"notes": notes.list_notes(session, limit=_int(q.get("limit"), "limit", 30))})
                if path == "/api/v1/lab/report-subscriptions":
                    return _json(start_response, 200, report_subscriptions.list_subscriptions(session, user))
                if path == "/api/v1/lab/completeness":
                    return _json(start_response, 200, channel_day_completeness(session, days=_int(q.get("days"), "days", 3)))
                body = _read_json(environ)
                if path == "/api/v1/lab/report-subscriptions/save":
                    return _json(start_response, 200, report_subscriptions.save_subscription(session, user, sub_id=body.get("id"), interval=body.get("interval"), layout=body.get("layout"), sections=body.get("sections"),
                                                                                          language=body.get("language"), segment=body.get("segment"), send_hour=body.get("send_hour")))
                if path == "/api/v1/lab/report-subscriptions/toggle":
                    return _json(start_response, 200, report_subscriptions.set_active(session, user, body.get("id"), bool(body.get("active"))))
                if path == "/api/v1/lab/report-subscriptions/delete":
                    return _json(start_response, 200, report_subscriptions.delete_subscription(session, user, body.get("id")))
                if path == "/api/v1/lab/report-subscriptions/send-now":
                    return _json(start_response, 200, report_subscriptions.send_now(session, user, body.get("id")))
                if path == "/api/v1/lab/alerts/list":
                    return _json(start_response, 200, alerts.list_alerts(session, user.id))
                if path == "/api/v1/lab/alerts/create":
                    alerts.create_alert(session, user.id, channel_id=body.get("channel_id"), kind=str(body.get("kind") or ""), threshold=body.get("threshold"),
                                        window_minutes=body.get("window_minutes", 10), cooldown_minutes=body.get("cooldown_minutes", 60))
                    return _json(start_response, 200, alerts.list_alerts(session, user.id))
                if path == "/api/v1/lab/alerts/delete":
                    alerts.delete_alert(session, user.id, body.get("alert_id"))
                    return _json(start_response, 200, alerts.list_alerts(session, user.id))
                if path == "/api/v1/lab/alerts/toggle":
                    alerts.toggle_alert(session, user.id, body.get("alert_id"), bool(body.get("active")))
                    return _json(start_response, 200, alerts.list_alerts(session, user.id))
                if path == "/api/v1/lab/alerts/seen":
                    alerts.mark_seen(session, user.id)
                    return _json(start_response, 200, alerts.list_alerts(session, user.id))
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
