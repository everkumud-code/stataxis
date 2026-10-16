"""The keys the platform connectors use. An administrator saves them in the workspace (Social media setup); they are kept on the server, shown only as the last four characters,
and the environment (STAXIS_META_TOKEN, STAXIS_META_IG_USER_ID, STAXIS_X_BEARER_TOKEN) overrides them. StatAxis never asks anyone for a platform password."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from collector.social.connectors import Credentials
from collector.storage import AppSetting

FIELDS = {   # field -> (setting key, environment variable, secret)
    "meta_token": ("social.meta_token", "STAXIS_META_TOKEN", True),
    "meta_ig_user_id": ("social.meta_ig_user_id", "STAXIS_META_IG_USER_ID", False),
    "x_bearer": ("social.x_bearer", "STAXIS_X_BEARER_TOKEN", True),
}
LIMIT_KEY = "social.x_max_per_run"        # how many X accounts one pass may read (X charges for reads)
DEFAULT_X_LIMIT = 50
INTERVAL_KEY = "social.hours_between"      # hours between two readings of an account
DEFAULT_INTERVAL = 6


def _get(session: Session, key: str) -> str:
    row = session.get(AppSetting, key)
    return (row.value or "").strip() if row else ""


def credentials(session: Session) -> Credentials:
    values = {name: os.getenv(env, "").strip() or _get(session, key) for name, (key, env, _secret) in FIELDS.items()}
    return Credentials(**values)


def x_limit(session: Session) -> int:
    try:
        return max(0, min(5000, int(_get(session, LIMIT_KEY) or DEFAULT_X_LIMIT)))
    except ValueError:
        return DEFAULT_X_LIMIT


def interval_hours(session: Session) -> int:
    try:
        return max(1, min(168, int(_get(session, INTERVAL_KEY) or DEFAULT_INTERVAL)))
    except ValueError:
        return DEFAULT_INTERVAL


def public_status(session: Session) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, (key, env, secret) in FIELDS.items():
        value = os.getenv(env, "").strip() or _get(session, key)
        out[name] = {"set": bool(value), "hint": (("…" + value[-4:]) if secret else value) if value else None, "source": "environment" if os.getenv(env, "").strip() else "workspace"}
    out["x_max_per_run"] = x_limit(session)
    out["hours_between"] = interval_hours(session)
    return out


def _set(session: Session, key: str, value: str, by: str) -> None:
    row = session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key)
        session.add(row)
    row.value, row.updated_by, row.updated_at = value, by, datetime.now(UTC)


def save(session: Session, by: str, values: dict[str, Any]) -> None:
    """Save the keys that were sent (an empty value leaves the saved one alone; ``clear_<field>`` removes it)."""
    for name, (key, _env, _secret) in FIELDS.items():
        raw = values.get(name)
        clear = bool(values.get("clear_" + name))
        if raw is None and not clear:
            continue
        value = "" if clear else str(raw).strip()
        if not clear and not value:
            continue
        if name == "meta_ig_user_id" and value and not value.isdigit():
            raise ValueError("the Instagram account id is a number")
        if name in ("meta_token", "x_bearer") and value and (len(value) < 20 or " " in value):
            raise ValueError("that does not look like an access token")
        _set(session, key, value, by)
    for field, key, low, high in (("x_max_per_run", LIMIT_KEY, 0, 5000), ("hours_between", INTERVAL_KEY, 1, 168)):
        if values.get(field) not in (None, ""):
            try:
                n = int(values[field])
            except (TypeError, ValueError):
                raise ValueError(f"{field} must be a whole number") from None
            if not low <= n <= high:
                raise ValueError(f"{field} must be between {low} and {high}")
            _set(session, key, str(n), by)
    session.commit()
