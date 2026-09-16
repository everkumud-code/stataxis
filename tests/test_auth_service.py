import pytest

from api.auth import AuthIdentity
from api.auth_service import authenticate, login, policy_for_identity, register
from collector.storage import User, create_database
from sqlalchemy.orm import Session


def make_session(tmp_path):
    engine = create_database(f"sqlite:///{tmp_path / 'auth.db'}")
    return Session(engine)


def register_application(session):
    return register(
        session,
        " Test@Example.org ",
        "correct horse battery",
        "Test User",
        "+91 9000000000",
        "Example Media Pvt Ltd",
        "Audience research",
        "SX Pro",
    )


def approve(session):
    user = session.query(User).one()
    user.approval_status = "approved"
    user.active = True
    user.plan = user.requested_plan
    session.commit()
    return user


def test_register_creates_pending_application(tmp_path, monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    session = make_session(tmp_path)
    payload = register_application(session)
    assert payload["email"] == "test@example.org"
    assert payload["plan"] == "sx_free"
    assert payload["requested_plan"] == "sx_pro"
    assert payload["approval_status"] == "pending"
    assert payload["is_admin"] is False
    user = session.query(User).one()
    assert user.password_hash != "correct horse battery"
    session.close()


def test_public_mailbox_registration_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    session = make_session(tmp_path)
    with pytest.raises(ValueError, match="custom organization email"):
        register(session, "user@gmail.com", "correct horse battery", "User", "+91 9000000000", "Example", "Research", "SX Pro")
    session.close()


def test_duplicate_registration_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    session = make_session(tmp_path)
    register_application(session)
    with pytest.raises(ValueError, match="already registered"):
        register(session, "TEST@example.org", "correct horse battery", "Test User", "+91 9000000000", "Example Media Pvt Ltd", "Audience research", "SX Pro")
    session.close()


def test_pending_login_is_blocked_until_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    session = make_session(tmp_path)
    register_application(session)
    with pytest.raises(PermissionError, match="pending admin approval"):
        login(session, "TEST@example.org", "correct horse battery")
    session.close()


def test_login_issues_token_after_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    session = make_session(tmp_path)
    register_application(session)
    approve(session)
    result = login(session, "TEST@example.org", "correct horse battery")
    identity = authenticate(f"Bearer {result['access_token']}")
    assert identity.email == "test@example.org"
    assert identity.plan == "sx_pro"
    session.close()


def test_login_rejects_wrong_password(tmp_path, monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    session = make_session(tmp_path)
    register_application(session)
    approve(session)
    with pytest.raises(PermissionError, match="invalid email or password"):
        login(session, "test@example.org", "wrong password")
    session.close()


def test_package_entitlement_is_server_resolved():
    identity = AuthIdentity(7, "user@example.com", "sx_free")
    policy = policy_for_identity(identity)
    assert not policy.can_evaluate_url
    assert not policy.can_download_report
    premium = policy_for_identity(AuthIdentity(8, "pro@example.com", "sx_pro"))
    assert premium.can_evaluate_url
    assert premium.can_download_report


def test_authentication_requires_bearer_token(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    with pytest.raises(PermissionError, match="authentication required"):
        authenticate(None)
    with pytest.raises(PermissionError, match="authentication required"):
        authenticate("Basic abc")
