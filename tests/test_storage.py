from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from collector.classification import VideoClassification
from collector.storage import Base, save_observations
from collector.youtube.collector import VideoObservation


def test_observations_are_append_only_and_duplicate_safe() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    observed_at = datetime.now(UTC)
    observation = VideoObservation(
        video_id="video1",
        channel_id="channel1",
        observed_at=observed_at,
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

        # Replaying the exact same measurement must not create a second row.
        saved = save_observations(
            session=session,
            channel_name="Test Channel",
            channel_youtube_id="channel1",
            network="Test Network",
            language="Hindi",
            observations=[observation],
        )
        assert saved == 0

        # A genuinely new timestamp remains append-only.
        observation_2 = VideoObservation(
            video_id="video1",
            channel_id="channel1",
            observed_at=observed_at + timedelta(minutes=2),
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


def test_save_observations_does_not_overwrite_curated_region_when_region_is_omitted() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    observation = VideoObservation(
        video_id="video-curated",
        channel_id="channel-curated",
        observed_at=datetime.now(UTC),
        title="Curated",
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
        save_observations(
            session, "Curated Channel", "channel-curated", "Network", "Hindi", [observation],
            region="Jharkhand",
        )
        save_observations(
            session, "Collector Name", "channel-curated", "youtube", "unknown", [observation],
        )
        from collector.storage import Channel
        channel = session.query(Channel).filter_by(youtube_channel_id="channel-curated").one()
        assert channel.region == "Jharkhand"
