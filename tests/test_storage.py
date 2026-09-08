from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from collector.classification import VideoClassification
from collector.storage import Base, save_observations
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
        classification=VideoClassification.LIVE.value,
        live_started_at=None,
        live_ended_at=None,
    )

    with Session(engine) as session:
        saved = save_observations(
            session=session,
            channel_name="Test Channel",
            channel_youtube_id="channel1",
            network="Test Network",
            language="Hindi",
            observations=[observation],
        )

        assert saved == 1

        observation_2 = VideoObservation(
            video_id="video1",
            channel_id="channel1",
            observed_at=datetime.now(timezone.utc),
            title="Test",
            published_at=None,
            view_count=150,
            like_count=12,
            comment_count=3,
            concurrent_viewers=35,
            is_live=True,
            classification=VideoClassification.LIVE.value,
            live_started_at=None,
            live_ended_at=None,
        )

        saved = save_observations(
            session=session,
            channel_name="Test Channel",
            channel_youtube_id="channel1",
            network="Test Network",
            language="Hindi",
            observations=[observation_2],
        )

        assert saved == 1

        rows = session.execute(
            Base.metadata.tables["stx_observations"].select()
        ).fetchall()

        assert len(rows) == 2
        assert rows[0].view_count == 100
        assert rows[1].view_count == 150