"""A person's own dashboard: six sections, each showing the data they chose, side by side on one screen.

The second section is always the STX Index (it cannot be changed to anything else, though it may be narrowed to a language and a category). The other five are chosen from the catalog below,
and every section can be narrowed to one language and one category (Main stream, Business news ...). The layout is kept with the login, so it follows the person to any device; it is
stored as one setting per person (no account table is touched) and checked on every save.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from api.me import LANGUAGES
from collector.storage import AppSetting, User
from metrics.markets import SEGMENTS

SLOTS = 6
FIXED_SLOT, FIXED_WIDGET = 1, "stx"   # the second section is the STX Index
WIDGETS: dict[str, str] = {
    "stx": "STX Index",
    "numbers": "Key numbers",
    "views": "Top channels by views gained (7 days)",
    "audience": "Top channels by average audience (today)",
    "movers": "Biggest movers (rank change)",
    "live": "Live now",
    "spikes": "Recent spikes",
    "forecasts": "Prime-time forecasts",
    "weekly": "Weekly views (last 7 days)",
    "alerts": "My alerts: what fired",
}
DEFAULT_WIDGETS = ["views", "stx", "audience", "movers", "live", "spikes"]


def _key(user: User) -> str:
    return f"dashboard.{user.id}"


def _slot(widget: Any, language: Any, segment: Any, index: int) -> dict[str, str]:
    widget = FIXED_WIDGET if index == FIXED_SLOT else str(widget or "")
    if widget not in WIDGETS:
        raise ValueError(f"section {index + 1}: choose one of the listed kinds of data")
    language, segment = str(language or "").strip(), str(segment or "").strip()
    if language and language not in LANGUAGES:
        raise ValueError(f"section {index + 1}: unknown language")
    if segment and segment not in SEGMENTS:
        raise ValueError(f"section {index + 1}: unknown category")
    return {"widget": widget, "language": language, "segment": segment}


def default_layout() -> list[dict[str, str]]:
    return [_slot(w, "", "news", i) for i, w in enumerate(DEFAULT_WIDGETS)]


def catalog() -> dict[str, Any]:
    return {"widgets": [{"id": k, "label": v} for k, v in WIDGETS.items()], "fixed": {"slot": FIXED_SLOT, "widget": FIXED_WIDGET}, "slot_count": SLOTS,
            "languages": LANGUAGES, "segments": [{"id": k, "label": v} for k, v in SEGMENTS.items()]}


def get_layout(session: Session, user: User) -> dict[str, Any]:
    row = session.get(AppSetting, _key(user))
    layout = None
    if row and row.value:
        try:
            raw = json.loads(row.value)
            layout = [_slot(s.get("widget"), s.get("language"), s.get("segment"), i) for i, s in enumerate(raw[:SLOTS])] if isinstance(raw, list) and len(raw) == SLOTS else None
        except (ValueError, AttributeError, TypeError):
            layout = None   # a layout that no longer validates (a widget was retired) gives way to the default
    return {"slots": layout or default_layout(), "customised": layout is not None, **catalog()}


def save_layout(session: Session, user: User, body: dict[str, Any]) -> dict[str, Any]:
    if body.get("reset"):
        row = session.get(AppSetting, _key(user))
        if row is not None:
            session.delete(row)
            session.commit()
        return get_layout(session, user)
    slots = body.get("slots")
    if not isinstance(slots, list) or len(slots) != SLOTS:
        raise ValueError(f"the dashboard has {SLOTS} sections")
    clean = [_slot(s.get("widget") if isinstance(s, dict) else None, s.get("language") if isinstance(s, dict) else None, s.get("segment") if isinstance(s, dict) else None, i) for i, s in enumerate(slots)]
    row = session.get(AppSetting, _key(user))
    if row is None:
        row = AppSetting(key=_key(user))
        session.add(row)
    row.value, row.updated_by, row.updated_at = json.dumps(clean), user.email, datetime.now(UTC)
    session.commit()
    return get_layout(session, user)
