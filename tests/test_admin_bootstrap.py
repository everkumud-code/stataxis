import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.admin_bootstrap import bootstrap_admin
from collector.storage import Base, User


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_bootstrap_admin_creates_approved_admin(session, monkeypatch):
    monkeypatch.setenv("STAXIS_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("STAXIS_ADMIN_PASSWORD", "a-valid-admin-password")

    assert bootstrap_admin(session) is True

    user = session.query(User).filter_by(email="admin@example.com").one()
    assert user.is_admin is True
    assert user.active is True
    assert user.approval_status == "approved"


def test_bootstrap_admin_promotes_existing_user_and_approves(session, monkeypatch):
    user = User(
        email="existing@example.com",
        password_hash="existing-hash",
        plan="sx_free",
        is_admin=False,
        active=False,
        approval_status="pending",
    )
    session.add(user)
    session.commit()

    monkeypatch.setenv("STAXIS_ADMIN_EMAIL", "existing@example.com")
    monkeypatch.setenv("STAXIS_ADMIN_PASSWORD", "a-valid-admin-password")

    assert bootstrap_admin(session) is True

    session.refresh(user)
    assert user.is_admin is True
    assert user.active is True
    assert user.approval_status == "approved"
