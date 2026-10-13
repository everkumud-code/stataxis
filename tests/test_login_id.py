"""A login ID can be any username the owner chooses; an email still works; renaming keeps everything else."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api import user_admin
from api.admin_bootstrap import bootstrap_admin
from api.auth import hash_password
from api.auth_service import clean_login_id, login
from collector.storage import Base, User


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("STAXIS_AUTH_SECRET", "x" * 40)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_the_rule_for_a_login_id():
    assert clean_login_id("  Kumud ") == "kumud"
    assert clean_login_id("desk.01@co") == "desk.01@co"
    for bad in ("ab", "has space", "x" * 65, "-leading", "semi;colon", "", None, 7):
        with pytest.raises(ValueError):
            clean_login_id(bad)


def test_an_account_made_with_a_username_can_sign_in_and_be_renamed(session):
    out = user_admin.create_user(session, email="Priya.Desk", name="Priya", organization="Firm", mobile="", plan="sx_pro")
    assert out["email"] == "priya.desk"
    assert login(session, "PRIYA.desk", out["temporary_password"])["account"]["email"] == "priya.desk"
    with pytest.raises(PermissionError):
        login(session, "someone-else", out["temporary_password"])
    renamed = user_admin.rename_login(session, out["id"], "priya")
    assert renamed["email"] == "priya" and renamed["plan"] == "sx_pro"
    assert login(session, "priya", out["temporary_password"])["token_type"] == "Bearer"
    with pytest.raises(PermissionError):
        login(session, "priya.desk", out["temporary_password"])


def test_a_login_id_cannot_be_taken_twice(session):
    a = user_admin.create_user(session, email="alpha", name="A", organization="O", mobile="", plan="sx_pro")
    user_admin.create_user(session, email="beta", name="B", organization="O2", mobile="", plan="sx_pro")
    with pytest.raises(ValueError, match="already uses"):
        user_admin.rename_login(session, a["id"], "BETA")


def test_an_admin_who_changed_their_login_id_does_not_get_a_second_admin_on_restart(session, monkeypatch):
    monkeypatch.setenv("STAXIS_ADMIN_EMAIL", "owner@example.com")
    monkeypatch.setenv("STAXIS_ADMIN_PASSWORD", "a-valid-admin-password")
    assert bootstrap_admin(session) is True
    owner = session.query(User).filter_by(email="owner@example.com").one()
    owner.email = "kumud"   # the administrator's login ID was changed in the database (the Users list no longer offers this for administrators)
    session.commit()
    assert bootstrap_admin(session) is False
    assert session.query(User).filter_by(is_admin=True).count() == 1
    assert login(session, "kumud", "a-valid-admin-password")["account"]["is_admin"] is True
