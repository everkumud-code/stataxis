from datetime import UTC, datetime

from sqlalchemy.orm import Session

from collector.classification import VideoClassification
from collector.storage import Channel, Observation, Video, create_database
from metrics.database_ranking import (
    build_current_channel_rankings,
    build_current_live_channel_rankings,
)


def _add_video(
    session: Session,
    channel: Channel,
    youtube_video_id: str,
    classification: str,
    view_count: int | None,
    concurrent_viewers: int | None,
    observed_at: datetime,
) -> None:
    video = Video(
        youtube_video_id=youtube_video_id,
        channel_id=channel.id,
        title=youtube_video_id,
    )
    session.add(video)
    session.flush()
    session.add(
        Observation(
            video_id=video.id,
            channel_id=channel.id,
            observed_at=observed_at,
            view_count=view_count,
            concurrent_viewers=concurrent_viewers,
            is_live=classification == VideoClassification.LIVE.value,
            classification=classification,
        )
    )


def test_current_rankings_separate_vod_views_from_live_audience():
    engine = create_database("sqlite:///:memory:")
    observed_at = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)

    with Session(engine) as session:
        channel = Channel(
            youtube_channel_id="channel-1",
            name="Alpha News",
            language="Hindi",
        )
        session.add(channel)
        session.flush()

        _add_video(session, channel, "regular-1", VideoClassification.REGULAR_VIDEO.value, 100, None, observed_at)
        _add_video(session, channel, "live-1", VideoClassification.LIVE.value, None, 50, observed_at)
        _add_video(session, channel, "upcoming-1", VideoClassification.UPCOMING.value, 999, None, observed_at)
        _add_video(session, channel, "completed-live-1", VideoClassification.COMPLETED_LIVE.value, 888, 777, observed_at)
        _add_video(session, channel, "unknown-1", VideoClassification.UNKNOWN.value, 666, 555, observed_at)
        session.commit()

        rankings = build_current_channel_rankings(session)

    assert len(rankings) == 1
    snapshot = rankings[0]
    assert snapshot.total_views == 100
    assert snapshot.video_count == 1
    assert snapshot.average_views == 100
    assert snapshot.average_concurrent == 50
    assert snapshot.peak_concurrent == 50


def test_current_rankings_use_latest_observation_for_each_video():
    engine = create_database("sqlite:///:memory:")
    first = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)
    latest = datetime(2026, 9, 13, 10, 5, tzinfo=UTC)

    with Session(engine) as session:
        channel = Channel(
            youtube_channel_id="channel-1",
            name="Alpha News",
            language="Hindi",
        )
        session.add(channel)
        session.flush()

        video = Video(
            youtube_video_id="regular-1",
            channel_id=channel.id,
            title="Regular",
        )
        session.add(video)
        session.flush()

        session.add_all(
            [
                Observation(
                    video_id=video.id,
                    channel_id=channel.id,
                    observed_at=first,
                    view_count=100,
                    classification=VideoClassification.REGULAR_VIDEO.value,
                ),
                Observation(
                    video_id=video.id,
                    channel_id=channel.id,
                    observed_at=latest,
                    view_count=150,
                    classification=VideoClassification.REGULAR_VIDEO.value,
                ),
            ]
        )
        session.commit()

        rankings = build_current_channel_rankings(session)

    assert rankings[0].total_views == 150
    assert rankings[0].video_count == 1


def test_current_live_rankings_order_by_live_audience():
    engine = create_database("sqlite:///:memory:")
    observed_at = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)

    with Session(engine) as session:
        for channel_id, name, concurrent in [
            ("channel-a", "Alpha", 100),
            ("channel-b", "Beta", 200),
            ("channel-c", "Gamma", 150),
        ]:
            channel = Channel(
                youtube_channel_id=channel_id,
                name=name,
                language="Hindi",
            )
            session.add(channel)
            session.flush()
            _add_video(
                session,
                channel,
                f"{channel_id}-live",
                VideoClassification.LIVE.value,
                None,
                concurrent,
                observed_at,
            )

        session.commit()
        rankings = build_current_live_channel_rankings(session)

    assert [item.name for item in rankings] == ["Beta", "Gamma", "Alpha"]
    assert [item.average_concurrent for item in rankings] == [200, 150, 100]
