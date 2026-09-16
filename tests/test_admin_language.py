import pytest

from api.admin import set_channel_language
from api.auth import AuthIdentity
from collector.storage import Channel, create_database
from sqlalchemy.orm import Session


def test_admin_language_override_persists() -> None:
    engine = create_database("sqlite:///:memory:")
    identity = AuthIdentity(1, "admin@example.com", "sx_enterprise", True)
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-test", name="Test", language="unknown")
        session.add(channel)
        session.commit()
        payload = set_channel_language(session, identity, channel.id, "Hindi")
        assert payload["language"] == "Hindi"
        assert session.get(Channel, channel.id).language == "Hindi"


def test_non_admin_cannot_override_language() -> None:
    engine = create_database("sqlite:///:memory:")
    identity = AuthIdentity(1, "user@example.com", "sx_pro", False)
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-test", name="Test", language="unknown")
        session.add(channel)
        session.commit()
        with pytest.raises(PermissionError):
            set_channel_language(session, identity, channel.id, "Hindi")
