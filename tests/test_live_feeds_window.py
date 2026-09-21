from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from api.live_monitor import live_audience_window
from collector.storage import Base, Channel, Observation, Video, create_database, save_observations
from collector.youtube.collector import VideoObservation

END = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _obs(video, at, viewers):
    return Observation(video_id=video.id, channel_id=video.channel_id, observed_at=at,
                       view_count=1, concurrent_viewers=viewers, is_live=True, source="test")


def _seed():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    channel = Channel(youtube_channel_id="c", name="News", network="n", language="Hindi", region="India", active=True)
    session.add(channel)
    session.flush()
    main = Video(youtube_video_id="main", channel_id=channel.id, title="24x7", live_started_at=END - timedelta(days=45))
    event = Video(youtube_video_id="event", channel_id=channel.id, title="Event", live_started_at=END - timedelta(hours=2))
    ended = Video(youtube_video_id="ended", channel_id=channel.id, title="Ended", live_started_at=END - timedelta(hours=3))
    session.add_all([main, event, ended])
    session.flush()
    return engine, session, channel, main, event, ended


def test_channel_reports_primary_secondary_and_all_feeds():
    engine, session, channel, main, event, ended = _seed()
    t = END - timedelta(minutes=1)
    session.add_all([
        _obs(main, t, 50_000), _obs(event, t + timedelta(seconds=5), 12_000),
        # Ended 30 minutes ago: its last live sample must not count towards "current".
        _obs(ended, t - timedelta(minutes=30), 7_000),
    ])
    session.commit()
    payload = live_audience_window(session, start_at=END - timedelta(hours=1), end_at=END)
    row = payload["channels"][0]
    assert row["feeds"]["primary"] == 50_000
    assert row["feeds"]["secondary"] == 12_000
    assert row["feeds"]["all"] == 62_000
    assert row["feeds"]["primary_video_id"] == "main"
    assert row["feeds"]["secondary_count"] == 1
    assert row["current_concurrent"] == 62_000
    assert payload["overall"]["current_concurrent"] == 62_000
    assert payload["overall"]["feeds"] == {"primary": 50_000, "secondary": 12_000, "all": 62_000}
    assert payload["languages"]["Hindi"]["current_concurrent"] == 62_000


def test_secondary_stream_no_longer_hides_the_primary_feed():
    """Regression: only the channel's single latest observation used to be counted."""
    engine, session, channel, main, event, ended = _seed()
    t = END - timedelta(minutes=1)
    session.add_all([_obs(main, t, 40_000), _obs(event, t + timedelta(seconds=1), 5_000)])
    session.commit()
    payload = live_audience_window(session, start_at=END - timedelta(hours=1), end_at=END)
    assert payload["overall"]["current_concurrent"] == 45_000


def test_channel_with_only_short_lived_streams_has_no_primary_but_full_all_feed():
    engine, session, channel, main, event, ended = _seed()
    main.live_started_at = END - timedelta(hours=1)
    t = END - timedelta(minutes=1)
    session.add_all([_obs(main, t, 9_000), _obs(event, t, 1_000)])
    session.commit()
    row = live_audience_window(session, start_at=END - timedelta(hours=1), end_at=END)["channels"][0]
    assert row["feeds"]["primary"] == 0
    assert row["feeds"]["all"] == 10_000


def _video_observation(video_id, started, ended=None):
    return VideoObservation(
        video_id=video_id, channel_id="c", observed_at=END, title="t", published_at=None,
        view_count=1, like_count=None, comment_count=None, concurrent_viewers=10, is_live=ended is None,
        classification="LIVE", live_started_at=started, live_ended_at=ended,
    )


def test_live_start_and_end_are_persisted_and_not_erased_by_later_partial_data():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        save_observations(session, "News", "c", "n", "Hindi", [_video_observation("v1", "2026-09-01T04:30:00Z")])
        video = session.query(Video).filter_by(youtube_video_id="v1").one()
        assert video.live_started_at.replace(tzinfo=UTC) == datetime(2026, 9, 1, 4, 30, tzinfo=UTC)
        assert video.live_ended_at is None
        later = _video_observation("v1", None, "2026-09-01T09:00:00Z")
        later = VideoObservation(**{**later.__dict__, "observed_at": END + timedelta(minutes=1)})
        save_observations(session, "News", "c", "n", "Hindi", [later])
        video = session.query(Video).filter_by(youtube_video_id="v1").one()
        assert video.live_started_at is not None
        assert video.live_ended_at is not None


def test_create_database_adds_live_columns_to_an_existing_database(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.db'}"
    old = create_engine(url)
    with old.begin() as connection:
        connection.execute(text("CREATE TABLE stx_users (id INTEGER PRIMARY KEY, email VARCHAR(320))"))
        connection.execute(text("CREATE TABLE stx_channels (id INTEGER PRIMARY KEY, youtube_channel_id VARCHAR(64))"))
        connection.execute(text("CREATE TABLE stx_videos (id INTEGER PRIMARY KEY, youtube_video_id VARCHAR(32), channel_id INTEGER, title TEXT, published_at VARCHAR(64))"))
    engine = create_database(url)
    with engine.connect() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(stx_videos)"))}
    assert {"live_started_at", "live_ended_at"} <= columns
