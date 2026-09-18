from api.errors import AuthenticationError
"""Password hashing and signed bearer-token primitives for StatAxis accounts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass


PBKDF2_ITERATIONS = 600_000
TOKEN_TTL_SECONDS = 86_400


@dataclass(frozen=True)
class AuthIdentity:
    """Authenticated account identity carried by a signed access token."""

    user_id: int
    email: str
    plan: str
    is_admin: bool = False


def _secret() -> bytes:
    value = os.getenv("STAXIS_AUTH_SECRET", "").strip()
    if not value:
        raise RuntimeError("STAXIS_AUTH_SECRET is required for authentication")
    return value.encode("utf-8")


def hash_password(password: str) -> str:
    """Hash a password with a unique salt using PBKDF2-HMAC-SHA256."""
    if len(password) < 12:
        raise ValueError("password must be at least 12 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """Verify a PBKDF2 password hash without leaking comparison timing."""
    try:
        algorithm, iterations, salt_b64, digest_b64 = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = _unb64(salt_b64)
        expected = _unb64(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def issue_token(identity: AuthIdentity, *, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    """Create an HMAC-SHA256 signed bearer token with a bounded lifetime."""
    if ttl_seconds <= 0:
        raise ValueError("token TTL must be positive")
    now = int(time.time())
    payload = {
        "sub": identity.user_id,
        "email": identity.email,
        "plan": identity.plan,
        "admin": identity.is_admin,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    encoded = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64(signature)}"


def verify_token(token: str) -> AuthIdentity:
    """Validate signature and expiry, returning the authenticated identity."""
    try:
        encoded, signature_b64 = token.split(".", 1)
        expected = hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(signature_b64)):
            raise ValueError("invalid token")
        payload = json.loads(_unb64(encoded).decode("utf-8"))
        if int(payload["exp"]) <= int(time.time()):
            raise ValueError("token expired")
        return AuthIdentity(
            user_id=int(payload["sub"]),
            email=str(payload["email"]),
            plan=str(payload["plan"]),
            is_admin=bool(payload.get("admin", False)),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid token") from exc


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
