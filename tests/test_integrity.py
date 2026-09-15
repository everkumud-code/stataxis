from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from collector.integrity import audit_database
from collector.storage import Channel, CollectionRun, Observation, Video, create_database


def test_integrity_audit_accepts_consistent_measurement_graph():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC123", name="Test")
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="vid123", channel_id=channel.id, title="Test")
        session.add(video)
        session.flush()
        session.add(
            Observation(
                video_id=video.id,
                channel_id=channel.id,
                observed_at=datetime.now(UTC),
                view_count=100,
                like_count=5,
                comment_count=2,
                concurrent_viewers=10,
            )
        )
        session.add(CollectionRun(started_at=datetime.now(UTC) - timedelta(seconds=1), status="success", channels_attempted=1, videos_observed=1, finished_at=datetime.now(UTC)))
        session.commit()

        report = audit_database(session)

        assert report.ok
        assert report.checked_channels == 1
        assert report.checked_videos == 1
        assert report.checked_observations == 1
        assert report.checked_collection_runs == 1
        assert report.issues == ()


def test_integrity_audit_detects_observation_channel_mismatch():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        first = Channel(youtube_channel_id="UC1", name="First")
        second = Channel(youtube_channel_id="UC2", name="Second")
        session.add_all([first, second])
        session.flush()
        video = Video(youtube_video_id="vid123", channel_id=first.id, title="Test")
        session.add(video)
        session.flush()
        session.add(Observation(video_id=video.id, channel_id=second.id, observed_at=datetime.now(UTC)))
        session.commit()

        report = audit_database(session)

        assert not report.ok
        assert any(issue.code == "observation_channel_mismatch" for issue in report.issues)


def test_integrity_audit_detects_view_count_regression():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-regression", name="Regression")
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="vid-regression", channel_id=channel.id, title="Regression")
        session.add(video)
        session.flush()
        session.add_all([
            Observation(video_id=video.id, channel_id=channel.id, observed_at=datetime(2026, 9, 15, 8, 0, tzinfo=UTC), view_count=100),
            Observation(video_id=video.id, channel_id=channel.id, observed_at=datetime(2026, 9, 15, 8, 1, tzinfo=UTC), view_count=90),
        ])
        session.commit()

        report = audit_database(session)

        assert not report.ok
        assert any(issue.code == "view_count_regression" for issue in report.issues)
