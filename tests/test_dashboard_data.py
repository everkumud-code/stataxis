from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from collector.storage import Base, Channel, ChannelStats, Observation, Video, create_database, save_observations
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
