from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from collector.storage import Base, Observation, save_observations
from collector.youtube.collector import VideoObservation


def test_observations_are_append_only() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    observation = VideoObservation(
        video_id="video1",
        channel_id="channel1",
        observed_at=datetime.now(timezone.utc),
        title="Test",
        published_at=None,
        view_count=100,
        like_count=10,
        comment_count=2,
        concurrent_viewers=25,
        is_live=True,
        live_started_at=None,
        live_ended_at=None,
    )

    with Session(engine) as session:
        assert save_observations(
            session,
            "Test Channel",
            "channel1",
            "Test Network",
            "Hindi",
            [observation],
        ) == 1
        observation2 = VideoObservation(**{**observation.__dict__, "view_count": 125})
        assert save_observations(
            session,
            "Test Channel",
            "channel1",
            "Test Network",
            "Hindi",
            [observation2],
        ) == 1
        assert session.query(Observation).count() == 2
