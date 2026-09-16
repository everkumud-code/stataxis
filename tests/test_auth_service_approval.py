import pytest
from sqlalchemy.orm import Session

from api.auth_service import login, register
from collector.storage import create_database


def test_registration_creates_pending_profile_without_workspace_login(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "test-secret")
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        payload = register(session, "analyst@acme.example", "long-enough-password", "Analyst", "+919999999999", "Acme", "Research", "SX Pro")
        assert payload["approval_status"] == "pending"
        with pytest.raises(PermissionError, match="pending admin approval"):
            login(session, "analyst@acme.example", "long-enough-password")


def test_consumer_email_is_rejected():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        with pytest.raises(ValueError, match="custom organization email"):
            register(session, "person@gmail.com", "long-enough-password", "Person", "9999999999", "Acme", "Research", "SX Pro")
