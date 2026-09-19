from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from collector.storage import Base, Channel, ChannelStats, Observation, Video, _add_column_if_missing, create_database, save_observations
from collector.topics import assign_topic
from collector.youtube.collector import VideoObservation


def test_assign_topic_supports_hindi_and_english_keywords():
    assert assign_topic("Election results and parliament update") == "Politics"
    assert assign_topic("लोकसभा चुनाव पर बड़ी खबर") == "Politics"
    assert assign_topic("Latest cricket match highlights") == "Sports"
    assert assign_topic("बॉलीवुड फिल्म का नया गाना") == "Entertainment"
    assert assign_topic("Share market and stock update") == "Business"
    assert assign_topic("A quiet travel story") == "Other"


def test_save_observations_persists_video_metadata_and_channel_stats():
    engine = create_database("sqlite:///:memory:")
    observed_at = datetime(2026, 9, 19, tzinfo=UTC)
    observation = VideoObservation(
        video_id="video-dashboard",
        channel_id="channel-dashboard",
        observed_at=observed_at,
        title="Election update",
        published_at="2026-09-18T10:00:00Z",
        view_count=1000,
        like_count=50,
        comment_count=10,
        concurrent_viewers=None,
        is_live=False,
        classification="REGULAR_VIDEO",
        live_started_at=None,
        live_ended_at=None,
        thumbnail_url="https://example.com/thumb.jpg",
        category_id="25",
        topic="Politics",
    )
    with Session(engine) as session:
        save_observations(
            session,
            "Dashboard Channel",
            "channel-dashboard",
            "Network",
            "Hindi",
            [observation],
            region="Jharkhand",
            avatar_url="https://example.com/avatar.jpg",
            handle="@dashboard",
            channel_stats=(observed_at, 10000, 500000, 100),
        )
        channel = session.query(Channel).one()
        video = session.query(Video).one()
        stats = session.query(ChannelStats).one()
        assert channel.avatar_url.endswith("avatar.jpg")
        assert channel.handle == "@dashboard"
        assert video.thumbnail_url.endswith("thumb.jpg")
        assert video.category_id == "25"
        assert video.topic == "Politics"
        assert stats.subscribers == 10000
        assert stats.total_views == 500000
        assert stats.video_count == 100


def test_create_database_migrates_dashboard_columns_safely():
    engine = create_database("sqlite:///:memory:")
    with engine.begin() as connection:
        channel_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(stx_channels)")}
        video_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(stx_videos)")}
        assert {"avatar_url", "handle"} <= channel_columns
        assert {"thumbnail_url", "category_id", "topic"} <= video_columns


def test_save_observations_backfills_topic_for_existing_video():
    engine = create_database("sqlite:///:memory:")
    observed_at = datetime(2026, 9, 19, tzinfo=UTC)
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="channel-backfill", name="Backfill", language="Hindi")
        session.add(channel)
        session.flush()
        video = Video(
            youtube_video_id="video-backfill",
            channel_id=channel.id,
            title="Election update",
            topic=None,
        )
        session.add(video)
        session.commit()

        observation = VideoObservation(
            video_id="video-backfill",
            channel_id="channel-backfill",
            observed_at=observed_at,
            title="Election update",
            published_at=None,
            view_count=100,
            like_count=5,
            comment_count=1,
            concurrent_viewers=None,
            is_live=False,
            classification="REGULAR_VIDEO",
            live_started_at=None,
            live_ended_at=None,
            thumbnail_url=None,
            category_id="25",
            topic=None,
        )
        save_observations(
            session,
            "Backfill",
            "channel-backfill",
            "Network",
            "Hindi",
            [observation],
        )
        assert session.query(Video).one().topic == "Politics"


def test_channel_stats_support_large_64_bit_values():
    engine = create_database("sqlite:///:memory:")
    observed_at = datetime(2026, 9, 19, tzinfo=UTC)
    with Session(engine) as session:
        save_observations(
            session,
            "Large Stats",
            "channel-large-stats",
            "Network",
            "Hindi",
            [],
            channel_stats=(observed_at, 41_000_000_000, 41_000_000_000, 41_000_000_000),
        )
        stats = session.query(ChannelStats).one()
        assert stats.subscribers == 41_000_000_000
        assert stats.total_views == 41_000_000_000
        assert stats.video_count == 41_000_000_000


def test_save_observations_does_not_overwrite_video_metadata_with_none():
    engine = create_database("sqlite:///:memory:")
    observed_at = datetime(2026, 9, 19, tzinfo=UTC)
    with Session(engine) as session:
        first = VideoObservation(
            video_id="video-metadata-preserve",
            channel_id="channel-metadata-preserve",
            observed_at=observed_at,
            title="Original title",
            published_at="2026-09-18T10:00:00Z",
            view_count=100,
            like_count=5,
            comment_count=1,
            concurrent_viewers=None,
            is_live=False,
            classification="REGULAR_VIDEO",
            live_started_at=None,
            live_ended_at=None,
            thumbnail_url="https://example.com/original.jpg",
            category_id="25",
            topic="Politics",
        )
        save_observations(
            session, "Metadata", "channel-metadata-preserve", "Network", "Hindi", [first]
        )
        second = VideoObservation(
            video_id="video-metadata-preserve",
            channel_id="channel-metadata-preserve",
            observed_at=observed_at + timedelta(minutes=1),
            title="Updated title",
            published_at="2026-09-18T10:00:00Z",
            view_count=200,
            like_count=6,
            comment_count=2,
            concurrent_viewers=None,
            is_live=False,
            classification="REGULAR_VIDEO",
            live_started_at=None,
            live_ended_at=None,
            thumbnail_url=None,
            category_id=None,
            topic=None,
        )
        save_observations(
            session, "Metadata", "channel-metadata-preserve", "Network", "Hindi", [second]
        )
        video = session.query(Video).one()
        assert video.title == "Updated title"
        assert video.thumbnail_url == "https://example.com/original.jpg"
        assert video.category_id == "25"
        assert video.topic == "Politics"


def test_dashboard_migration_ignores_duplicate_column_race():
    class Dialect:
        name = "sqlite"

    class Connection:
        dialect = Dialect()

        def execute(self, statement):
            assert "ADD COLUMN" in str(statement)
            raise RuntimeError("duplicate column name: handle")

    _add_column_if_missing(Connection(), "stx_channels", "handle", "VARCHAR(255)", set())
