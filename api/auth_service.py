"""Account registration, approval, login, and authenticated capability resolution."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from api.access import VideoAccessPolicy, plan_video_access_policy
from api.auth import AuthIdentity, hash_password, issue_token, verify_password
from api.auth import verify_token
from api.errors import AuthenticationError
from api.plans import SXPlan, get_plan
from collector.storage import User

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PUBLIC_EMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "hotmail.com",
    "outlook.com", "live.com", "icloud.com", "proton.me", "protonmail.com",
    "aol.com", "rediffmail.com", "mail.com", "gmx.com", "zoho.com",
})
_DUMMY_PASSWORD_HASH = "pbkdf2_sha256$600000$AQEBAQEBAQEBAQEBAQEBAQ$qVMnbrzFRpnP-Sb4fsnYsDWHHcJSbJktHlJ96uK82i0"


def register(session: Session, email: str, password: str, full_name: str, mobile: str,
             organization: str, purpose_of_use: str, requested_plan: str) -> dict:
    normalized = email.strip().lower()
    if not _EMAIL_RE.fullmatch(normalized):
        raise ValueError("valid organization email is required")
    domain = normalized.rsplit("@", 1)[-1]
    if domain in _PUBLIC_EMAIL_DOMAINS:
        raise ValueError("custom organization email is required")
    try:
        plan = get_plan(requested_plan).code.value
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    for value, label, limit in ((full_name, "name", 255), (mobile, "mobile number", 32),
                                (organization, "organization", 255), (purpose_of_use, "purpose of use", 2000)):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
            raise ValueError(f"{label} is required")
    if session.query(User).filter_by(email=normalized).one_or_none() is not None:
        return {"already_exists": True}
    user = User(email=normalized, password_hash=hash_password(password), plan=SXPlan.FREE.value,
                approval_status="pending", full_name=full_name.strip(), mobile=mobile.strip(),
                organization=organization.strip(), purpose_of_use=purpose_of_use.strip(), requested_plan=plan)
    session.add(user)
    session.commit()
    return account_payload(user)


def login(session: Session, email: str, password: str) -> dict:
    normalized = email.strip().lower()
    user = session.query(User).filter_by(email=normalized, active=True).one_or_none()
    if user is None:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        raise PermissionError("invalid email or password")
    if not verify_password(password, user.password_hash):
        raise PermissionError("invalid email or password")
    if not user.is_admin and user.approval_status != "approved":
        raise PermissionError("profile pending admin approval")
    if not user.is_admin and user.requested_plan:
        user.plan = user.requested_plan
        session.commit()
    identity = AuthIdentity(user.id, user.email, user.plan, user.is_admin)
    return {"access_token": issue_token(identity), "token_type": "Bearer", "account": account_payload(user)}


def authenticate(authorization: str | None) -> AuthIdentity:
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthenticationError("authentication required")
    token = authorization[7:].strip()
    if not token:
        raise AuthenticationError("authentication required")
    try:
        return verify_token(token)
    except ValueError as exc:
        raise AuthenticationError("authentication required") from exc


def policy_for_identity(identity: AuthIdentity) -> VideoAccessPolicy:
    if identity.is_admin:
        return VideoAccessPolicy(True, True, True, True, "admin access")
    return plan_video_access_policy(identity.plan)


def account_payload(user: User) -> dict:
    return {"id": user.id, "email": user.email, "plan": user.plan, "requested_plan": user.requested_plan,
            "approval_status": user.approval_status, "is_admin": user.is_admin, "active": user.active,
            "full_name": user.full_name, "organization": user.organization}
