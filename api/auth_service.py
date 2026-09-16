"""Account registration, login, and authenticated capability resolution."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from api.access import VideoAccessPolicy, plan_video_access_policy
from api.auth import AuthIdentity, hash_password, issue_token, verify_password, verify_token
from api.plans import SXPlan
from collector.storage import User

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def register(session: Session, email: str, password: str) -> dict:
    """Create a new free account and return a safe public account payload."""
    normalized = email.strip().lower()
    if not _EMAIL_RE.fullmatch(normalized):
        raise ValueError("valid email is required")
    if session.query(User).filter_by(email=normalized).one_or_none() is not None:
        raise ValueError("email already registered")
    user = User(email=normalized, password_hash=hash_password(password), plan=SXPlan.FREE.value)
    session.add(user)
    session.commit()
    return account_payload(user)


def login(session: Session, email: str, password: str) -> dict:
    """Authenticate an account and issue a signed access token."""
    normalized = email.strip().lower()
    user = session.query(User).filter_by(email=normalized, active=True).one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise PermissionError("invalid email or password")
    identity = AuthIdentity(user.id, user.email, user.plan, user.is_admin)
    return {"access_token": issue_token(identity), "token_type": "Bearer", "account": account_payload(user)}


def authenticate(authorization: str | None) -> AuthIdentity:
    """Resolve a bearer Authorization header into a signed identity."""
    if not authorization or not authorization.startswith("Bearer "):
        raise PermissionError("authentication required")
    token = authorization[7:].strip()
    if not token:
        raise PermissionError("authentication required")
    return verify_token(token)


def policy_for_identity(identity: AuthIdentity) -> VideoAccessPolicy:
    """Resolve capabilities from server-signed identity, never client role headers."""
    if identity.is_admin:
        return VideoAccessPolicy(True, True, True, True, "admin access")
    return plan_video_access_policy(identity.plan)


def account_payload(user: User) -> dict:
    return {"id": user.id, "email": user.email, "plan": user.plan, "is_admin": user.is_admin, "active": user.active}
