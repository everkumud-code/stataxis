"""Getting back into an account after the password is forgotten (an administrator's too).

Two ways, both ending with the person choosing a new password on the "forgot password" page:
  * an e-mail code: asked for by login ID, sent to the account's e-mail address (when the login ID is one), valid for thirty minutes, used once;
  * backup codes: eight codes the person makes while signed in (and keeps somewhere safe), each used once, no expiry. They work even when e-mail delivery is not set up.
A third way, for the server owner, is `python -m api.admin_reset` (see that file).

Rules that keep it safe: only a hash of a code is stored and it is tied to the account; the answer to "forgot" is the same whether or not the account exists; a wrong, used, expired or foreign code all give
the same answer; tries are limited by address and by account; a new e-mail code cancels the earlier ones; a successful reset cancels every unused e-mail code. A reset does not end sessions already open
(sign-in tokens last 24 hours and are not kept on the server).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from sqlalchemy.orm import Session

from api.auth import hash_password
from collector.storage import RecoveryCode, User

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0, O, 1, I: a code read from paper cannot be mistaken
EMAIL_CODE_MINUTES = 30
BACKUP_COUNT = 8
NOT_VALID = "That code is not valid, or it has expired. Ask for a new one."
SENT = "If that account exists and has an e-mail address, a reset code has been sent. It works for 30 minutes."
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def normalise(code: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(code or "").upper())


def _hash(user_id: int, code: str) -> str:
    return hashlib.sha256(f"stx-recovery:{user_id}:{normalise(code)}".encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def can_email(user: User) -> bool:
    return bool(_EMAIL.fullmatch(user.email or ""))


def make_backup_codes(session: Session, user_id: int) -> list[str]:
    """Eight fresh backup codes (shown once, by the caller); the unused older ones stop working."""
    for old in session.query(RecoveryCode).filter(RecoveryCode.user_id == user_id, RecoveryCode.kind == "backup", RecoveryCode.used_at.is_(None)).all():
        session.delete(old)
    codes = [new_code() for _ in range(BACKUP_COUNT)]
    for c in codes:
        session.add(RecoveryCode(user_id=user_id, code_hash=_hash(user_id, c), kind="backup", created_at=_now()))
    session.commit()
    return codes


def backup_status(session: Session, user_id: int) -> dict[str, Any]:
    rows = session.query(RecoveryCode).filter(RecoveryCode.user_id == user_id, RecoveryCode.kind == "backup").all()
    unused = [r for r in rows if r.used_at is None]
    made = max((_aware(r.created_at) for r in rows), default=None)
    return {"unused": len(unused), "made_at": made.isoformat() if made else None, "email_possible": can_email(session.get(User, user_id)) if session.get(User, user_id) else False}


def issue_email_code(session: Session, login: str, *, now: datetime | None = None) -> tuple[User, str] | None:
    """A thirty-minute code for the account, or None when there is no active account with an e-mail login ID. The earlier unused e-mail codes are cancelled."""
    user = session.query(User).filter_by(email=login, active=True).one_or_none()
    if user is None or not can_email(user):
        return None
    now = now or _now()
    for old in session.query(RecoveryCode).filter(RecoveryCode.user_id == user.id, RecoveryCode.kind == "email", RecoveryCode.used_at.is_(None)).all():
        session.delete(old)
    code = new_code()
    session.add(RecoveryCode(user_id=user.id, code_hash=_hash(user.id, code), kind="email", created_at=now, expires_at=now + timedelta(minutes=EMAIL_CODE_MINUTES)))
    session.commit()
    return user, code


def reset_password(session: Session, login: str, code: Any, new_password: Any, *, now: datetime | None = None) -> User:
    """Use a code to set a new password. Every refusal about the code is the same sentence, so nothing is learnt about which accounts or codes exist."""
    if not isinstance(new_password, str) or len(new_password) < 12:
        raise ValueError("new password must be at least 12 characters")
    if len(new_password) > 256:
        raise ValueError("new password is too long")
    now = now or _now()
    user = session.query(User).filter_by(email=login, active=True).one_or_none()
    digest = _hash(user.id if user else 0, code)
    row = None
    if user is not None:
        row = session.query(RecoveryCode).filter(RecoveryCode.user_id == user.id, RecoveryCode.code_hash == digest, RecoveryCode.used_at.is_(None)).first()
    if row is None or not hmac.compare_digest(row.code_hash, digest) or (row.expires_at is not None and _aware(row.expires_at) <= now):
        raise ValueError(NOT_VALID)
    row.used_at = now
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    for other in session.query(RecoveryCode).filter(RecoveryCode.user_id == user.id, RecoveryCode.kind == "email", RecoveryCode.used_at.is_(None)).all():
        session.delete(other)
    session.commit()
    return user


def email_text(code: str, login: str, base_url: str) -> tuple[str, str, str]:
    link = f"{base_url}/forgot#login={login}&code={code}"
    text = (f"Someone asked to reset the password of the StatAxis account {login}.\n\nYour code: {code}\nIt works for {EMAIL_CODE_MINUTES} minutes and only once.\n\nOpen {link} and choose a new password.\n\n"
            "If you did not ask for this, ignore this e-mail: your password has not changed.\n")
    html = (f"<p>Someone asked to reset the password of the StatAxis account <b>{login}</b>.</p><p>Your code: <b style=\"font-size:20px;letter-spacing:2px\">{code}</b><br>It works for {EMAIL_CODE_MINUTES} minutes and only once.</p>"
            f"<p><a href=\"{link}\">Choose a new password</a></p><p>If you did not ask for this, ignore this e-mail: your password has not changed.</p>")
    return "Your StatAxis password reset code", html, text


def send_in_background(session_factory: Callable[[], Session], to: str, subject: str, html: str, text: str) -> None:
    """Send the mail on a thread of its own, so the answer to the person never waits for (or reveals) the mail service. A mail that cannot be sent is dropped silently."""
    def run() -> None:
        from api import mailer
        session = session_factory()
        try:
            mailer.send_email(session, to=to, subject=subject, html=html, text=text)
        except Exception:   # noqa: BLE001 - no key, refused or unreachable: the person can still use a backup code
            pass
        finally:
            session.close()
    threading.Thread(target=run, daemon=True).start()
