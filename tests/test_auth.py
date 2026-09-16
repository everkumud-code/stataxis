import pytest

from api.auth import AuthIdentity, hash_password, issue_token, verify_password, verify_token


def test_password_hash_is_salted_and_verifiable(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    first = hash_password("correct horse battery")
    second = hash_password("correct horse battery")
    assert first != second
    assert verify_password("correct horse battery", first)
    assert not verify_password("wrong password", first)


def test_password_policy_rejects_short_password(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    with pytest.raises(ValueError, match="12 characters"):
        hash_password("too-short")


def test_signed_token_round_trip(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    identity = AuthIdentity(7, "user@example.com", "sx_pro")
    token = issue_token(identity)
    assert verify_token(token) == identity


def test_signed_token_rejects_tampering(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    token = issue_token(AuthIdentity(7, "user@example.com", "sx_pro"))
    encoded, signature = token.split(".", 1)
    tampered = encoded[:-1] + ("A" if encoded[-1] != "A" else "B") + "." + signature
    with pytest.raises(ValueError, match="invalid token"):
        verify_token(tampered)


def test_expired_token_is_rejected(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    token = issue_token(AuthIdentity(7, "user@example.com", "sx_pro"), ttl_seconds=1)
    monkeypatch.setattr("api.auth.time.time", lambda: 9_999_999_999)
    with pytest.raises(ValueError, match="invalid token"):
        verify_token(token)
