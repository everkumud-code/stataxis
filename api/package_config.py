"""Persisted configuration for future StatAxis commercial package slots."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from collector.storage import PackageConfig

MIN_SLOT = 5
MAX_SLOT = 40


def ensure_package_slots(session: Session) -> None:
    """Create empty reserved slots once; never overwrite commercial choices."""
    existing = {row.slot for row in session.query(PackageConfig).all()}
    changed = False
    for slot in range(MIN_SLOT, MAX_SLOT + 1):
        if slot not in existing:
            session.add(PackageConfig(slot=slot, name=None, criteria_json="[]", amount=None, currency="INR", active=False))
            changed = True
    if changed:
        session.commit()


def list_package_slots(session: Session) -> list[dict[str, Any]]:
    ensure_package_slots(session)
    rows = session.query(PackageConfig).filter(PackageConfig.slot.between(MIN_SLOT, MAX_SLOT)).order_by(PackageConfig.slot.asc()).all()
    return [_payload(row) for row in rows]


def update_package_slot(session: Session, slot: int, payload: dict[str, Any]) -> dict[str, Any]:
    if not MIN_SLOT <= slot <= MAX_SLOT:
        raise ValueError(f"slot must be between {MIN_SLOT} and {MAX_SLOT}")
    row = session.query(PackageConfig).filter_by(slot=slot).one_or_none()
    if row is None:
        row = PackageConfig(slot=slot, name=None, criteria_json="[]", amount=None, currency="INR", active=False)
        session.add(row)

    if "name" in payload:
        name = payload["name"]
        if name is not None and (not isinstance(name, str) or len(name.strip()) > 120):
            raise ValueError("name must be a string up to 120 characters or null")
        row.name = name.strip() if isinstance(name, str) and name.strip() else None

    if "criteria" in payload:
        criteria = payload["criteria"]
        if not isinstance(criteria, list) or len(criteria) > 100:
            raise ValueError("criteria must be a list of up to 100 items")
        if any(not isinstance(item, str) or len(item.strip()) > 160 for item in criteria):
            raise ValueError("each criterion must be a string up to 160 characters")
        row.criteria_json = json.dumps([item.strip() for item in criteria if item.strip()], ensure_ascii=False)

    if "amount" in payload:
        amount = payload["amount"]
        if amount is None or amount == "":
            row.amount = None
        else:
            try:
                value = Decimal(str(amount))
            except (InvalidOperation, ValueError) as exc:
                raise ValueError("amount must be a valid non-negative number") from exc
            if value < 0 or value > Decimal("999999999999"):
                raise ValueError("amount must be between 0 and 999999999999")
            row.amount = value

    if "currency" in payload:
        currency = payload["currency"]
        if not isinstance(currency, str) or len(currency.strip()) != 3:
            raise ValueError("currency must be a 3-letter code")
        row.currency = currency.strip().upper()

    if "active" in payload:
        if not isinstance(payload["active"], bool):
            raise ValueError("active must be boolean")
        row.active = payload["active"]

    session.commit()
    session.refresh(row)
    return _payload(row)


def _payload(row: PackageConfig) -> dict[str, Any]:
    return {
        "slot": row.slot,
        "name": row.name,
        "criteria": json.loads(row.criteria_json or "[]"),
        "amount": float(row.amount) if row.amount is not None else None,
        "currency": row.currency,
        "active": row.active,
        "configured": bool(row.name or json.loads(row.criteria_json or "[]") or row.amount is not None),
    }
