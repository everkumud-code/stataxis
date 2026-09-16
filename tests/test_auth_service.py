import pytest

from api.auth import AuthIdentity
from api.auth_service import authenticate, login, policy_for_identity, register
from collector.storage import User, create_database
from sqlalchemy.orm import Session


def make_session(tmp_path):
    engine = create_database(f"sqlite:///{tmp_path / 'auth.db'}")
    return Session(engine)


def register_test_user(session):
    return register(
        session,
        " Test@Example.com ",
        "correct horse battery",
        "Test User",
        "+91-9000000000",
        "Example Media Pvt Ltd",
        "Media intelligence evaluation",
        "sx_free",
    )


def test_register_creates_free_account(tmp_path, monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    session = make_session(tmp_path)
    payload = register_test_user(session)
    assert payload["email"] == "test@example.com"
    assert payload["plan"] == "sx_free"
    assert payload["requested_plan"] == "sx_free"
    assert payload["approval_status"] == "pending"
    assert payload["is_admin"] is False
    user = session.query(User).one()
    assert user.password_hash != "correct horse battery"
    session.close()


def test_duplicate_registration_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    session = make_session(tmp_path)
    register_test_user(session)
    with pytest.raises(ValueError, match="already registered"):
        register(session, "TEST@example.com", "correct horse battery", "Test User", "+91-9000000000", "Example Media Pvt Ltd", "Media intelligence evaluation", "sx_free")
    session.close()


def test_login_requires_approval_before_workspace_access(tmp_path, monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    session = make_session(tmp_path)
    register_test_user(session)
    with pytest.raises(PermissionError, match="pending admin approval"):
        login(session, "TEST@example.com", "correct horse battery")
    session.close()


def test_login_issues_token_for_approved_user(tmp_path, monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    session = make_session(tmp_path)
    register_test_user(session)
    user = session.query(User).one()
    user.approval_status = "approved"
    session.commit()
    result = login(session, "TEST@example.com", "correct horse battery")
    identity = authenticate(f"Bearer {result['access_token']}")
    assert identity.email == "test@example.com"
    assert identity.plan == "sx_free"
    session.close()


def test_login_rejects_wrong_password(tmp_path, monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    session = make_session(tmp_path)
    register_test_user(session)
    with pytest.raises(PermissionError, match="invalid email or password"):
        login(session, "test@example.com", "wrong password")
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
