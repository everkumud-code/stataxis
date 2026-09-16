"""Safe first-admin bootstrap for production deployments."""

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from api.auth import hash_password
from api.plans import SXPlan
from collector.storage import User


def bootstrap_admin(session: Session) -> bool:
    """Create or promote the configured bootstrap admin; never log the password."""
    email = os.getenv("STAXIS_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("STAXIS_ADMIN_PASSWORD", "")
    if not email or not password:
        return False

    user = session.query(User).filter_by(email=email).one_or_none()
    if user is None:
        user = User(
            email=email,
            password_hash=hash_password(password),
            plan=SXPlan.ENTERPRISE.value,
            is_admin=True,
            active=True,
        )
        session.add(user)
    else:
        user.is_admin = True
        user.active = True
        user.plan = SXPlan.ENTERPRISE.value
    session.commit()
    return True
