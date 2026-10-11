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
            "approval_status": user.approval_status, "active": user.active, "is_admin": user.is_admin, "must_change_password": bool(user.must_change_password), "created_at": user.created_at.isoformat() if user.created_at else None}


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
    query = session.query(User).filter(User.is_admin.is_(False))   # administrator accounts are never in this list: nothing here can switch one off, reset it or rename it
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


ADMIN_NOT_HERE = "administrator accounts are not managed in this list; an administrator changes their own password under Profile"


def _manageable(session: Session, user_id: int) -> User:
    """A person on the Users list. An administrator is not one of them: this is how an administrator can never lock themselves out from here."""
    user = _get(session, user_id)
    if user.is_admin:
        raise ValueError(ADMIN_NOT_HERE)
    return user


def set_plan(session: Session, user_id: int, plan: str) -> dict[str, Any]:
    user = _manageable(session, user_id)
    code = get_plan(plan).code.value
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
    user = _manageable(session, user_id)
    if active:
        check_seat(session, user.organization, user.plan, exclude_user_id=user.id)
    user.active = bool(active)
    session.commit()
    return payload(user)


def _temp_password() -> str:
    return secrets.token_urlsafe(12)


def create_user(session: Session, *, email: str, name: str, organization: str, mobile: str, plan: str) -> dict[str, Any]:
    from api.auth_service import clean_login_id
    email = clean_login_id(email)
    if not (name or "").strip() or not (organization or "").strip():
        raise ValueError("name and organisation are required")
    if session.query(User).filter_by(email=email).one_or_none() is not None:
        raise ValueError("an account with this login ID already exists")
    code = get_plan(plan).code.value
    check_seat(session, organization, code)
    temp = _temp_password()
    user = User(email=email, password_hash=hash_password(temp), plan=code, requested_plan=code, is_admin=False, active=True, approval_status="approved", full_name=name.strip(),
                organization=organization.strip(), mobile=(mobile or "").strip() or None, must_change_password=True)
    session.add(user)
    session.commit()
    return {**payload(user), "temporary_password": temp, "note": "Shown once. Give it to the user: they must choose their own password the first time they sign in with it."}


def rename_login(session: Session, user_id: int, new_id: str) -> dict[str, Any]:
    """Change the ID a person signs in with. The password, package and privileges stay as they are."""
    from api.auth_service import clean_login_id
    user = _manageable(session, user_id)
    new_id = clean_login_id(new_id)
    other = session.query(User).filter(User.email == new_id, User.id != user.id).one_or_none()
    if other is not None:
        raise ValueError("another account already uses this login ID")
    user.email = new_id
    session.commit()
    return payload(user)


def reset_password(session: Session, user_id: int) -> dict[str, Any]:
    user = _manageable(session, user_id)
    temp = _temp_password()
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    session.commit()
    return {**payload(user), "temporary_password": temp, "note": "Shown once. Give it to the user: they must choose their own password the first time they sign in with it."}
