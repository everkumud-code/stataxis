"""A person's own account: which screens they may open, which screens they chose to see, and their profile.

Two separate things decide what a screen list looks like:
  * what the person MAY use: their package and whatever an administrator ticked for them (api/feature_access.py). The server enforces this where it can.
  * what the person WANTS to see: the choices they make on their first sign-in (who they are in the market, which screens, which languages and groups) and can change any time.
The list a person sees is the screens they may use, narrowed to the ones they chose. Nobody sees a screen they may not use, and nobody is shown screens they have no use for.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from api import feature_access
from collector.storage import User, UserPref
from metrics.markets import KNOWN_LANGUAGES, SEGMENTS

# every screen of the workspace that a person may use: (id, label, the feature that gates it)
VIEWS: list[tuple[str, str, str]] = [
    ("briefing", "Briefing: findings for my role", "briefing"), ("overview", "Overview", "overview"), ("market", "Market", "market"), ("channel", "Channel", "channel"),
    ("dashboard", "Channel dashboard", "dashboard"), ("stream", "Streams", "streams"), ("content", "Content", "content"), ("competition", "Competition", "competition"),
    ("trends", "Audience and trends", "trends"), ("live", "Live audience", "live"), ("stx", "STX Index", "stx"), ("changed", "What changed", "changed"),
    ("research", "Research signals", "research"), ("evaluate", "Evaluate a video", "evaluate"), ("weekly", "Weekly report", "weekly"), ("primetime", "Prime time", "prime_time"),
    ("builder", "Report builder", "report_builder"), ("creators", "IFX Score", "creators"), ("planner", "Media planner", "planner"), ("authenticity", "Authenticity radar", "authenticity"),
    ("audience", "Audience (geography and age)", "audience"), ("liveevent", "Live event compare", "live_compare"),
    ("operations", "Operations", "operations"), ("integrity", "Data integrity", "integrity"),
    ("spikes", "Spikes and movement", "spikes"), ("forecasts", "Forecasts", "forecasts"), ("notes", "Notes", "notes"), ("alerts", "Alerts", "alerts"), ("completeness", "Data completeness", "integrity"), ("reportmail", "Report e-mails", "report_email"),
]
VIEW_FEATURE = {vid: feature for vid, _label, feature in VIEWS}
ALWAYS = ("mychannels", "profile")   # every login has these two
PERSONAS: dict[str, tuple[str, list[str]]] = {
    "media": ("Media company", ["briefing", "overview", "market", "channel", "stream", "competition", "live", "stx", "changed", "weekly", "primetime", "liveevent", "builder"]),
    "buyer": ("Media buyer or agency", ["briefing", "market", "channel", "stx", "weekly", "primetime", "planner", "audience", "authenticity", "builder", "liveevent"]),
    "politician": ("Politician or campaign", ["briefing", "market", "live", "liveevent", "primetime", "weekly", "changed", "audience"]),
    "influencer": ("Influencer or journalist", ["briefing", "creators", "stx", "content", "trends", "audience", "authenticity"]),
    "audience": ("Audience member", ["briefing", "overview", "market", "live", "stx"]),
}
LANGUAGES = [*KNOWN_LANGUAGES, "Regional", "Other"]
SEGMENT_CHOICES = [(k, v) for k, v in SEGMENTS.items()]


def allowed_features(session: Session, user: User) -> list[str]:
    return [k for k in feature_access.FEATURES if feature_access.allowed(session, k, user.plan, user.is_admin, user.id)]


def _load(raw: str | None, default: Any) -> Any:
    try:
        value = json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def _row(session: Session, user_id: int) -> UserPref | None:
    return session.query(UserPref).filter_by(user_id=user_id).one_or_none()


def preferences(session: Session, user: User) -> dict[str, Any]:
    row = _row(session, user.id)
    return {"persona": row.persona if row else None, "views": _load(row.views_json, []) if row and row.views_json else None, "languages": _load(row.languages_json, []) if row else [],
            "segments": _load(row.segments_json, []) if row else [], "start_view": row.start_view if row else None, "job_title": row.job_title if row else None,
            "onboarded": bool(row and row.onboarded_at)}


def nav_views(session: Session, user: User) -> list[str]:
    """The screens this person sees: those they may use, narrowed to the ones they chose (a persona's usual set when they chose none one by one)."""
    allowed = set(allowed_features(session, user))
    may = [vid for vid, _l, feature in VIEWS if feature in allowed]
    prefs = preferences(session, user)
    chosen = prefs["views"] if prefs["views"] is not None else (PERSONAS[prefs["persona"]][1] if prefs["persona"] in PERSONAS else None)
    if not feature_access.packages_enabled(session):
        chosen = None   # packages are off: everyone sees every screen they may use; what they chose is kept for when packages are back
    shown = [v for v in may if chosen is None or v in chosen]
    return shown or may   # never an empty list: if every choice is something the person may not use, they see what they may use


def me_payload(session: Session, user: User) -> dict[str, Any]:
    from api.auth_service import account_payload

    allowed = set(allowed_features(session, user))
    prefs = preferences(session, user)
    nav = nav_views(session, user)
    start = prefs["start_view"] if prefs["start_view"] in nav or prefs["start_view"] in ALWAYS else (nav[0] if nav else "profile")
    return {"account": {**account_payload(user), "job_title": prefs["job_title"], "mobile": user.mobile}, "features": sorted(allowed),
            "views": [{"id": vid, "label": label, "feature": feature, "allowed": feature in allowed} for vid, label, feature in VIEWS],
            "personas": [{"id": k, "label": label, "views": views} for k, (label, views) in PERSONAS.items()], "languages": LANGUAGES, "segments": [{"id": k, "label": v} for k, v in SEGMENT_CHOICES],
            "preferences": prefs, "nav": nav, "always": list(ALWAYS), "start_view": start, "must_change_password": bool(user.must_change_password),
            "packages_enabled": feature_access.packages_enabled(session), "menu_choices_on": feature_access.packages_enabled(session)}


def set_preferences(session: Session, user: User, body: dict[str, Any]) -> dict[str, Any]:
    persona = str(body.get("persona") or "").strip() or None
    if persona is not None and persona not in PERSONAS:
        raise ValueError("choose who you are from the list")
    ids = {vid for vid, _l, _f in VIEWS}
    views = body.get("views")
    if views is not None:
        if not isinstance(views, list) or any(v not in ids for v in views):
            raise ValueError("views must be screen names from the list")
        views = list(dict.fromkeys(views))
    languages = body.get("languages") or []
    segments = body.get("segments") or []
    if not isinstance(languages, list) or any(x not in LANGUAGES for x in languages):
        raise ValueError("languages must be Hindi, English or Regional")
    if not isinstance(segments, list) or any(x not in SEGMENTS for x in segments):
        raise ValueError("groups must be names from the list")
    start = str(body.get("start_view") or "").strip() or None
    if start is not None and start not in ids and start not in ALWAYS:
        raise ValueError("choose a start screen from the list")
    row = _row(session, user.id)
    if row is None:
        row = UserPref(user_id=user.id)
        session.add(row)
    row.persona, row.views_json = persona, (json.dumps(views) if views is not None else None)
    row.languages_json, row.segments_json, row.start_view = json.dumps(languages), json.dumps(segments), start
    row.onboarded_at = row.onboarded_at or datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    session.commit()
    return me_payload(session, user)


def update_profile(session: Session, user: User, body: dict[str, Any]) -> dict[str, Any]:
    """The details a person may change about themselves. The login ID, the package and the organisation are the administrator's to change (seats are counted by organisation)."""
    name = str(body.get("full_name") or "").strip()
    mobile = str(body.get("mobile") or "").strip()
    title = str(body.get("job_title") or "").strip()
    if not name or len(name) > 255:
        raise ValueError("name is required (up to 255 characters)")
    if len(mobile) > 32 or (mobile and not all(c.isdigit() or c in "+-() " for c in mobile)):
        raise ValueError("mobile number may hold digits, spaces and + - ( ) only (up to 32 characters)")
    if len(title) > 120:
        raise ValueError("job title is too long (up to 120 characters)")
    user.full_name, user.mobile = name, mobile or None
    row = _row(session, user.id)
    if row is None:
        row = UserPref(user_id=user.id)
        session.add(row)
    row.job_title, row.updated_at = title or None, datetime.now(UTC)
    session.commit()
    return me_payload(session, user)
