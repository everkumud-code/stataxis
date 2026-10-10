"""Admin tools for accounts: list, change package, switch off or on, create with a one-time temporary password, reset a password, and the seat limit of a package."""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from api.auth import hash_password
from api.plans import get_plan
from collector.storage import User


def payload(user: User) -> dict[str, Any]:
    return {"id": user.id, "name": user.full_name, "email": user.email, "mobile": user.mobile, "organization": user.organization, "plan": user.plan, "requested_plan": user.requested_plan,
            "approval_status": user.approval_status, "active": user.active, "is_admin": user.is_admin, "created_at": user.created_at.isoformat() if user.created_at else None}


def seats_used(session: Session, organization: str | None, plan: str, exclude_user_id: int | None = None) -> int:
    if not organization or not organization.strip():
        return 0
    q = session.query(func.count(User.id)).filter(func.lower(User.organization) == organization.strip().lower(), User.plan == plan, User.active.is_(True),
                                                     User.approval_status == "approved", User.is_admin.is_(False))
    if exclude_user_id is not None:
        q = q.filter(User.id != exclude_user_id)
    return int(q.scalar() or 0)


def check_seat(session: Session, organization: str | None, plan: str, exclude_user_id: int | None = None) -> None:
    """A package with a seat limit (SX Corporate: 5) cannot give another seat to an organisation that already uses them all."""
    definition = get_plan(plan)
    if definition.max_seats is None:
        return
    used = seats_used(session, organization, definition.code.value, exclude_user_id)
    if used >= definition.max_seats:
        raise ValueError(f"{definition.name} has {definition.max_seats} seats and {organization or 'this organisation'} already uses {used}.")


def list_users(session: Session, *, q: str = "", plan: str = "", status: str = "") -> list[dict[str, Any]]:
    query = session.query(User)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.filter(func.lower(User.email).like(like) | func.lower(func.coalesce(User.full_name, "")).like(like) | func.lower(func.coalesce(User.organization, "")).like(like))
    if plan:
        query = query.filter(User.plan == get_plan(plan).code.value)
    if status:
        query = query.filter(User.approval_status == status)
    out = []
    for u in query.order_by(User.created_at.desc()).limit(500).all():
        p = payload(u)
        definition = get_plan(u.plan)
        p["plan_name"] = definition.name
        p["seats"] = {"used": seats_used(session, u.organization, u.plan), "max": definition.max_seats} if definition.max_seats else None
        out.append(p)
    return out


def _get(session: Session, user_id: int) -> User:
    user = session.get(User, int(user_id))
    if user is None:
        raise LookupError("user not found")
    return user


def set_plan(session: Session, user_id: int, plan: str) -> dict[str, Any]:
    user = _get(session, user_id)
    code = get_plan(plan).code.value
    if user.is_admin:
        raise ValueError("an administrator's package cannot be changed")
    if code != user.plan:
        check_seat(session, user.organization, code, exclude_user_id=user.id)
    user.plan = code
    user.requested_plan = code
    session.commit()
    return payload(user)


def set_active(session: Session, user_id: int, active: bool, acting_user_id: int) -> dict[str, Any]:
    user = _get(session, user_id)
    if user.id == acting_user_id and not active:
        raise ValueError("you cannot switch off your own account")
    if user.is_admin and not active and session.query(User).filter(User.is_admin.is_(True), User.active.is_(True), User.id != user.id).count() == 0:
        raise ValueError("this is the last active administrator")
    if active:
        check_seat(session, user.organization, user.plan, exclude_user_id=user.id)
    user.active = bool(active)
    session.commit()
    return payload(user)


def _temp_password() -> str:
    return secrets.token_urlsafe(12)


def create_user(session: Session, *, email: str, name: str, organization: str, mobile: str, plan: str) -> dict[str, Any]:
    email = (email or "").strip().lower()
    if "@" not in email or " " in email or len(email) > 320:
        raise ValueError("a valid email is required")
    if not (name or "").strip() or not (organization or "").strip():
        raise ValueError("name and organisation are required")
    if session.query(User).filter_by(email=email).one_or_none() is not None:
        raise ValueError("an account with this email already exists")
    code = get_plan(plan).code.value
    check_seat(session, organization, code)
    temp = _temp_password()
    user = User(email=email, password_hash=hash_password(temp), plan=code, requested_plan=code, is_admin=False, active=True, approval_status="approved", full_name=name.strip(),
                organization=organization.strip(), mobile=(mobile or "").strip() or None)
    session.add(user)
    session.commit()
    return {**payload(user), "temporary_password": temp, "note": "Shown once. Give it to the user and ask them to change it at once (Change password in the workspace)."}


def reset_password(session: Session, user_id: int) -> dict[str, Any]:
    user = _get(session, user_id)
    temp = _temp_password()
    user.password_hash = hash_password(temp)
    session.commit()
    return {**payload(user), "temporary_password": temp, "note": "Shown once. Give it to the user and ask them to change it at once."}
