"""Flexible commercial package metadata helpers."""
from __future__ import annotations

import json
from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session
from collector.storage import PackageConfig


def ensure_flexible_column(session: Session) -> None:
    """Add extensible commercial metadata without disturbing existing package rows."""
    bind = session.get_bind()
    inspector = __import__("sqlalchemy").inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("stx_package_configs")}
    if "flexible_json" not in cols:
        with bind.begin() as conn:
            conn.execute(text("ALTER TABLE stx_package_configs ADD COLUMN flexible_json TEXT DEFAULT '{}'"))


def read_flexible(session: Session, row: PackageConfig) -> dict[str, Any]:
    ensure_flexible_column(session)
    raw = session.execute(text("SELECT flexible_json FROM stx_package_configs WHERE id=:id"), {"id": row.id}).scalar()
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def write_flexible(session: Session, row: PackageConfig, *, privileges: list[str] | None = None,
                   duration_value: int | None = None, duration_unit: str | None = None) -> dict[str, Any]:
    ensure_flexible_column(session)
    data = read_flexible(session, row)
    if privileges is not None:
        data["privileges"] = privileges
    if duration_value is not None or duration_unit is not None:
        if duration_value is None or duration_unit is None:
            raise ValueError("duration value and duration unit must be provided together")
        data["duration_value"] = duration_value
        data["duration_unit"] = duration_unit
    session.execute(text("UPDATE stx_package_configs SET flexible_json=:data WHERE id=:id"), {"data": json.dumps(data, ensure_ascii=False), "id": row.id})
    session.commit()
    return data
