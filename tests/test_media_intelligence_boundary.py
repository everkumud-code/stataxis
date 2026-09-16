from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.media_intelligence import market_report
from collector.storage import Base, Channel, Observation, Video


def test_previous_market_window_excludes_shared_boundary():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = Session(engine)
    channel = Channel(youtube_channel_id="a", name="Alpha", language="Hindi", region="India")
    session.add(channel)
    session.flush()
    video = Video(youtube_video_id="v", channel_id=channel.id, title="Live")
    session.add(video)
    session.flush()
    as_of = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    session.add(Observation(video_id=video.id, channel_id=channel.id, observed_at=as_of - timedelta(hours=1), view_count=100, is_live=True, classification="LIVE"))
    session.add(Observation(video_id=video.id, channel_id=channel.id, observed_at=as_of, view_count=200, is_live=True, classification="LIVE"))
    session.commit()

    payload = market_report(session, as_of=as_of, period="1h", language="Hindi", region="India")
    assert payload["provenance"]["observation_count"] == 2
    assert payload["provenance"]["previous_observation_count"] == 0
