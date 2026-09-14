from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from collector.storage import Channel, Observation, Video, create_database
from metrics.persisted import build_persisted_video_snapshot


def _seed(session: Session) -> int:
    channel = Channel(youtube_channel_id="UC-test", name="Test Channel")
    session.add(channel)
    session.flush()
    video = Video(
        youtube_video_id="video-test",
        channel_id=channel.id,
        title="Measured story",
    )
    session.add(video)
    session.flush()
    start = datetime(2026, 9, 14, tzinfo=timezone.utc)
    session.add_all(
        [
            Observation(
                video_id=video.id, channel_id=channel.id,
                observed_at=start, view_count=1000, concurrent_viewers=100,
                classification="VOD",
            ),
            Observation(
                video_id=video.id, channel_id=channel.id,
                observed_at=start + timedelta(minutes=1),
                view_count=1120, concurrent_viewers=130, classification="VOD",
            ),
            Observation(
                video_id=video.id, channel_id=channel.id,
                observed_at=start + timedelta(minutes=2),
                view_count=1280, concurrent_viewers=170, classification="VOD",
            ),
        ]
    )
    session.commit()
    return video.id


def test_persisted_observations_feed_real_signals_into_index_and_view():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        video_id = _seed(session)
        result = build_persisted_video_snapshot(session, video_id)

        assert result.intelligence.index.score is not None
        assert result.intelligence.index.available_signals == 4
        assert result.intelligence.view.confidence == result.intelligence.index.confidence
        assert result.contributions


def test_persisted_adapter_is_read_only():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        video_id = _seed(session)
        before = session.query(Observation).count()
        build_persisted_video_snapshot(session, video_id)
        assert session.query(Observation).count() == before


def test_persisted_adapter_rejects_missing_video():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        with pytest.raises(ValueError, match="video 999 not found"):
            build_persisted_video_snapshot(session, 999)


def test_persisted_adapter_does_not_invent_signals_from_one_observation():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        video_id = _seed(session)
        session.query(Observation).filter(Observation.video_id == video_id).delete()
        session.add(
            Observation(
                video_id=video_id, channel_id=1,
                observed_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
                view_count=100, concurrent_viewers=10, classification="VOD",
            )
        )
        session.commit()
        result = build_persisted_video_snapshot(session, video_id)
        assert result.intelligence.index.score is None
        assert result.contributions == ()
