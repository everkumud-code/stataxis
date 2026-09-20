import pytest

from api.auth_service import login
from collector.storage import create_database
from sqlalchemy.orm import Session


def test_login_uses_dummy_hash_for_unknown_email(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("api.auth_service.verify_password", lambda password, encoded: calls.append(encoded) or False)
    engine = create_database(f"sqlite:///{tmp_path / 'auth-security.db'}")
    session = Session(engine)
    with pytest.raises(PermissionError, match="invalid email or password"):
        login(session, "missing@example.com", "correct horse battery")
    assert len(calls) == 1
    assert calls[0].startswith("pbkdf2_sha256$600000$")
    session.close()
