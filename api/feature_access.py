"""Which package may use which tool. The defaults are a starting point; an admin changes them in the workspace and the change applies at once."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from api.errors import AuthenticationError, AuthorizationError
from api.plans import SXPlan, all_plans, get_plan
from collector.storage import AppSetting, FeatureAccess, User, UserFeatureOverride

PLAN_ORDER = [plan.value for plan in SXPlan]
FEATURES: dict[str, tuple[str, str]] = {
    "overview": ("Overview of the market today", SXPlan.FREE.value),
    "market": ("Market view by group and language", SXPlan.FREE.value),
    "channel": ("Channel view", SXPlan.FREE.value),
    "stx": ("STX Index", SXPlan.FREE.value),
    "dashboard": ("Channel dashboard", SXPlan.IDEA.value),
    "streams": ("Streams", SXPlan.IDEA.value),
    "content": ("Content: what each channel published", SXPlan.IDEA.value),
    "trends": ("Audience and trends over time", SXPlan.IDEA.value),
    "changed": ("What changed", SXPlan.IDEA.value),
    "evaluate": ("Evaluate a video and download its report", SXPlan.IDEA.value),
    "competition": ("Competition between channels", SXPlan.INTELLIGENCE.value),
    "live": ("Live audience", SXPlan.INTELLIGENCE.value),
    "research": ("Research signals: tone and topics in titles", SXPlan.INTELLIGENCE.value),
    "operations": ("Operations: how collection is running", SXPlan.CORPORATE.value),
    "integrity": ("Data integrity checks", SXPlan.CORPORATE.value),
    "spikes": ("Spikes and audience movement", SXPlan.INTELLIGENCE.value),
    "forecasts": ("Prime-time forecasts and their track record", SXPlan.ANALYST.value),
    "notes": ("Daily and weekly notes", SXPlan.FREE.value),
    "alerts": ("Alerts on channels", SXPlan.IDEA.value),
    "briefing": ("Briefing: findings for your role", SXPlan.FREE.value),
    "weekly": ("Weekly views report", SXPlan.IDEA.value),
    "prime_time": ("Prime-time audience report", SXPlan.IDEA.value),
    "report_builder": ("Report builder with PDF download", SXPlan.IDEA.value),
    "creators": ("IFX Score (creators)", SXPlan.INTELLIGENCE.value),
    "planner": ("Media planner for advertisers", SXPlan.ANALYST.value),
    "live_compare": ("Live event compare (up to 30 channels)", SXPlan.INTELLIGENCE.value),
    "authenticity": ("Authenticity radar (unusual viewership)", SXPlan.PRO.value),
    "audience": ("Audience geography and age", SXPlan.ANALYST.value),
    "data_export": ("Excel data exports (machine-readable)", SXPlan.ANALYST.value),
}
DESCRIPTIONS = {
    "spikes": "Sudden rises in a channel's live audience with the stream that carried them, and who gained while who lost in the same minutes.",
    "forecasts": "What StatAxis expected each channel's prime-time audience to be, written down before the slot and scored afterwards, with the hit rate.",
    "notes": "A dated note on what the data said, written each day and each week by the findings engine.",
    "alerts": "Alerts on a channel's live audience (a level, a rise or a fall), shown inside StatAxis.",
    "operations": "How collection is running: channels tracked, last pass, readiness.",
    "integrity": "Checks on the stored data: gaps and inconsistencies, with the evidence.",
    "overview": "The state of the market today: who leads, what changed, and where to look next.",
    "market": "Channels grouped by language and group, with period and share.",
    "channel": "One channel: audience, views, growth, rank and movement.",
    "stx": "The STX Index for channels, with its confidence and its parts.",
    "dashboard": "A channel's dashboard: overview, STX trend and media intelligence on one screen.",
    "streams": "Primary and secondary live streams of a channel.",
    "content": "Videos, Shorts and live streams a channel published, with how each performed.",
    "trends": "How a channel's total views and audience moved over time.",
    "changed": "The videos that moved, with the evidence attached.",
    "evaluate": "Check one public video and download its report.",
    "competition": "Channels, markets and periods compared without hiding uncertainty.",
    "live": "The live audience of each channel right now, sampled every minute.",
    "research": "Tone and topics in titles, with the method and confidence stated.",
    "briefing": "Findings for your role, with what to do about them. Without the higher package a person sees the headlines only.",
    "weekly": "Views of every video uploaded in the chosen dates, per channel, with each channel's share, and a picture card to post.",
    "prime_time": "Average live viewers for each evening hour, top channels per hour.",
    "report_builder": "Pick days, hours, live / videos / Shorts, feed and genre, then download a branded PDF.",
    "creators": "The IFX Score (Impact, Followership, eXposure) for creators and independent journalists.",
    "live_compare": "Up to 30 channels covering a live event, side by side, with STX and the tone of what each is showing.",
    "planner": "Media planner: cost per 1,000 live viewers, target audience match and a suggested split of a budget.",
    "authenticity": "The authenticity radar: viewership that looks unusual, with the evidence.",
    "audience": "Audience geography and age, where a channel or a study supplied it.",
    "data_export": "Excel files with the raw numbers. These are machine-readable, unlike the branded PDF and picture cards.",
}


def packages_enabled(session: Session) -> bool:
    """True when packages decide what a person may use. An administrator can switch packages off: then every login may use every screen (a tick an administrator un-ticked for one person still holds)."""
    cached = session.info.get("_packages_enabled")
    if cached is None:
        row = session.get(AppSetting, "packages_enabled")
        cached = True if row is None else row.value == "1"
        session.info["_packages_enabled"] = cached
    return cached


def set_packages_enabled(session: Session, enabled: bool, by: str) -> dict[str, object]:
    row = session.get(AppSetting, "packages_enabled")
    if row is None:
        row = AppSetting(key="packages_enabled")
        session.add(row)
    row.value, row.updated_by, row.updated_at = ("1" if enabled else "0"), by, datetime.now(UTC)
    session.commit()
    session.info.pop("_packages_enabled", None)
    return {"packages_enabled": bool(enabled)}


def plan_rank(plan: str) -> int:
    return PLAN_ORDER.index(plan) if plan in PLAN_ORDER else 0


def matrix(session: Session) -> list[dict[str, object]]:
    rows = {r.feature: r for r in session.query(FeatureAccess).all()}
    out = []
    for key, (label, default) in FEATURES.items():
        row = rows.get(key)
        out.append({"feature": key, "label": label, "min_plan": row.min_plan if row else default, "default": default, "changed": bool(row and row.min_plan != default),
                    "updated_by": row.updated_by if row else None})
    return out


def min_plan_for(session: Session, feature: str) -> str:
    row = session.query(FeatureAccess).filter_by(feature=feature).one_or_none()
    return row.min_plan if row else FEATURES[feature][1]


def override_for(session: Session, user_id: int | None, feature: str) -> UserFeatureOverride | None:
    return session.query(UserFeatureOverride).filter_by(user_id=user_id, feature=feature).one_or_none() if user_id else None


def allowed(session: Session, feature: str, plan: str, is_admin: bool, user_id: int | None = None) -> bool:
    """An administrator may use everything. Otherwise what the admin ticked for this person decides; with no tick, the package does."""
    if feature not in FEATURES:
        raise ValueError("unknown feature")
    if is_admin:
        return True
    row = override_for(session, user_id, feature)
    if row is not None:
        return bool(row.allowed)
    if not packages_enabled(session):
        return True
    return plan_rank(plan) >= plan_rank(min_plan_for(session, feature))


def explain_denied(session: Session, feature: str, plan: str, user_id: int | None = None) -> str:
    row = override_for(session, user_id, feature)
    if row is not None and not row.allowed:
        return f"{FEATURES[feature][0]} has been switched off for your account by your admin."
    need = get_plan(min_plan_for(session, feature))
    mine = get_plan(plan) if plan in PLAN_ORDER else get_plan(SXPlan.FREE)
    return f"{FEATURES[feature][0]} is part of {need.name} and above. Your package is {mine.name}. Ask your admin to move you up."


def set_min_plan(session: Session, feature: str, plan: str, by: str) -> dict[str, object]:
    if feature not in FEATURES:
        raise ValueError("unknown feature")
    code = get_plan(plan).code.value  # raises for an unknown package
    row = session.query(FeatureAccess).filter_by(feature=feature).one_or_none()
    if row is None:
        row = FeatureAccess(feature=feature, min_plan=code, updated_by=by)
        session.add(row)
    else:
        row.min_plan, row.updated_by, row.updated_at = code, by, datetime.now(UTC)
    session.commit()
    return next(m for m in matrix(session) if m["feature"] == feature)


def user_matrix(session: Session, user: User) -> list[dict[str, object]]:
    """Every tool with whether this person may use it, why (their package or a tick by an admin) and what the package alone would say."""
    overrides = {r.feature: r for r in session.query(UserFeatureOverride).filter_by(user_id=user.id).all()}
    out = []
    for key, (label, _default) in FEATURES.items():
        by_package = user.is_admin or plan_rank(user.plan) >= plan_rank(min_plan_for(session, key))
        row = overrides.get(key)
        out.append({"feature": key, "label": label, "description": DESCRIPTIONS.get(key, ""), "allowed": True if user.is_admin else (bool(row.allowed) if row else by_package),
                    "by_package": by_package, "source": "admin" if row else "package", "min_plan": min_plan_for(session, key), "set_by": row.set_by if row else None})
    return out


def set_user_feature(session: Session, user_id: int, feature: str, value: bool | None, by: str) -> list[dict[str, object]]:
    """value True / False = a tick or an un-tick for this person; None = remove it, so the package decides again."""
    if feature not in FEATURES:
        raise ValueError("unknown feature")
    user = session.get(User, int(user_id))
    if user is None:
        raise LookupError("user not found")
    if user.is_admin:
        raise ValueError("an administrator can use everything; there is nothing to change")
    row = override_for(session, user.id, feature)
    if value is None:
        if row is not None:
            session.delete(row)
    elif row is None:
        session.add(UserFeatureOverride(user_id=user.id, feature=feature, allowed=bool(value), set_by=by))
    else:
        row.allowed, row.set_by, row.set_at = bool(value), by, datetime.now(UTC)
    session.commit()
    return user_matrix(session, user)


def require_export(session_factory: Any, *, user_id: int | None, plan: str, is_admin: bool) -> None:
    """The machine-readable Excel exports are their own privilege. The account record decides (so a change works at once); with no record the login's own package is used."""
    session = session_factory()
    try:
        user = session.get(User, int(user_id)) if user_id else None
        if user is not None and not user.active:
            raise AuthenticationError("authentication required")
        p, a = (user.plan, user.is_admin) if user is not None else (plan, is_admin)
        if not allowed(session, "data_export", p, a, user.id if user is not None else None):
            raise AuthorizationError(explain_denied(session, "data_export", p, user.id if user is not None else None))
    finally:
        session.close()


def plans_overview() -> list[dict[str, object]]:
    return [{"code": p.code.value, "name": p.name, "promise": p.promise, "max_seats": p.max_seats} for p in all_plans()]
