"""Persisted, admin-editable configuration for StatAxis commercial package slots."""
from __future__ import annotations
import json
from decimal import Decimal, InvalidOperation
from typing import Any
from sqlalchemy.orm import Session
from collector.storage import PackageConfig
from api.package_flex import ensure_flexible_column, read_flexible, write_flexible

MIN_SLOT = 5
MAX_SLOT = 40
DURATION_UNITS = {"day", "week", "month", "quarter", "year"}

def ensure_package_slots(session: Session) -> None:
    ensure_flexible_column(session)
    existing = {row.slot for row in session.query(PackageConfig).all()}
    changed = False
    for slot in range(MIN_SLOT, MAX_SLOT + 1):
        if slot not in existing:
            session.add(PackageConfig(slot=slot, name=None, criteria_json="[]", amount=None, currency="INR", active=False)); changed = True
    if changed: session.commit()

def list_package_slots(session: Session) -> list[dict[str, Any]]:
    ensure_package_slots(session)
    rows = session.query(PackageConfig).filter(PackageConfig.slot.between(MIN_SLOT, MAX_SLOT)).order_by(PackageConfig.slot.asc()).all()
    return [_payload(row, read_flexible(session, row)) for row in rows]

def update_package_slot(session: Session, slot: int, payload: dict[str, Any]) -> dict[str, Any]:
    if not MIN_SLOT <= slot <= MAX_SLOT: raise ValueError(f"slot must be between {MIN_SLOT} and {MAX_SLOT}")
    ensure_flexible_column(session)
    row = session.query(PackageConfig).filter_by(slot=slot).one_or_none()
    if row is None:
        row = PackageConfig(slot=slot, name=None, criteria_json="[]", amount=None, currency="INR", active=False); session.add(row); session.flush()
    if "name" in payload:
        name = payload["name"]
        if name is not None and (not isinstance(name, str) or len(name.strip()) > 120): raise ValueError("name must be a string up to 120 characters or null")
        row.name = name.strip() if isinstance(name, str) and name.strip() else None
    if "criteria" in payload:
        criteria = payload["criteria"]
        if not isinstance(criteria, list) or len(criteria) > 100 or any(not isinstance(x, str) or len(x.strip()) > 160 for x in criteria): raise ValueError("criteria must be a list of up to 100 strings")
        row.criteria_json = json.dumps([x.strip() for x in criteria if x.strip()], ensure_ascii=False)
    privileges = payload.get("privileges") if "privileges" in payload else None
    if privileges is not None and (not isinstance(privileges, list) or len(privileges) > 100 or any(not isinstance(x, str) or len(x.strip()) > 160 for x in privileges)): raise ValueError("privileges must be a list of up to 100 strings")
    if "amount" in payload:
        amount = payload["amount"]
        if amount is None or amount == "": row.amount = None
        else:
            try: value = Decimal(str(amount))
            except (InvalidOperation, ValueError) as exc: raise ValueError("amount must be a valid non-negative number") from exc
            if value < 0 or value > Decimal("999999999999"): raise ValueError("amount must be between 0 and 999999999999")
            row.amount = value
    if "currency" in payload:
        currency = payload["currency"]
        if not isinstance(currency, str) or len(currency.strip()) != 3: raise ValueError("currency must be a 3-letter code")
        row.currency = currency.strip().upper()
    duration_value = duration_unit = None
    if "duration_value" in payload or "duration_unit" in payload:
        try: duration_value = int(payload.get("duration_value"))
        except (TypeError, ValueError) as exc: raise ValueError("duration_value must be a positive integer") from exc
        duration_unit = str(payload.get("duration_unit", "")).strip().lower()
        if duration_value <= 0 or duration_value > 9999 or duration_unit not in DURATION_UNITS: raise ValueError("duration must be a positive value with unit day, week, month, quarter or year")
    if "active" in payload:
        if not isinstance(payload["active"], bool): raise ValueError("active must be boolean")
        row.active = payload["active"]
    session.flush()
    flexible = write_flexible(session, row, privileges=privileges, duration_value=duration_value, duration_unit=duration_unit)
    session.refresh(row)
    return _payload(row, flexible)

def _payload(row: PackageConfig, flexible: dict[str, Any]) -> dict[str, Any]:
    criteria = json.loads(row.criteria_json or "[]"); privileges = flexible.get("privileges", [])
    return {"slot": row.slot, "name": row.name, "criteria": criteria, "privileges": privileges, "amount": float(row.amount) if row.amount is not None else None, "currency": row.currency, "duration_value": flexible.get("duration_value"), "duration_unit": flexible.get("duration_unit"), "active": row.active, "configured": bool(row.name or criteria or privileges or row.amount is not None or flexible.get("duration_value"))}
