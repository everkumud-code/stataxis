from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.catalog import list_channels
from collector.storage import Base, Channel


def test_list_channels_returns_active_channels_in_name_order():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Channel(youtube_channel_id="B", name="Beta", active=True),
            Channel(youtube_channel_id="A", name="Alpha", active=True),
            Channel(youtube_channel_id="X", name="Hidden", active=False),
        ])
        session.commit()

        assert [item["name"] for item in list_channels(session)] == ["Alpha", "Beta"]
