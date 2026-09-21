from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from collector import retention
from collector.retention import (
    MAX_API_DATA_DAYS,
    MAX_STATS_MONTHS,
    TITLE_PLACEHOLDER,
    RetentionConfig,
    months_ago,
    run_retention,
    run_retention_if_due,
)
from collector.storage import Channel, ChannelStats, Observation, Video, create_database, save_observations
from collector.youtube.collector import VideoObservation
from metrics.persistence import IntelligenceSnapshotRecord

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _session() -> Session:
    return Session(create_database("sqlite:///:memory:"))


def _channel(session: Session, refreshed: datetime | None, *, avatar: str | None = "https://img/a.png", handle: str | None = "@news") -> Channel:
    channel = Channel(
        youtube_channel_id=f"UC{session.query(Channel).count()}",
        name="News One",
        avatar_url=avatar,
        handle=handle,
        api_refreshed_at=refreshed,
    )
    session.add(channel)
    session.flush()
    return channel


def _video(session: Session, channel: Channel, refreshed: datetime | None, key: str = "v1") -> Video:
    video = Video(
        youtube_video_id=key,
        channel_id=channel.id,
        title="Real title",
        thumbnail_url="https://img/t.jpg",
        category_id="25",
        topic="politics",
        published_at="2026-09-01T00:00:00Z",
        api_refreshed_at=refreshed,
    )
    session.add(video)
    session.flush()
    return video


def _observation(session: Session, video: Video, observed_at: datetime) -> None:
    session.add(Observation(video_id=video.id, channel_id=video.channel_id, observed_at=observed_at, view_count=10))


def test_months_ago_uses_calendar_months_and_clamps_day() -> None:
    assert months_ago(datetime(2026, 3, 31, tzinfo=UTC), 1) == datetime(2026, 2, 28, tzinfo=UTC)
    assert months_ago(datetime(2028, 3, 31, tzinfo=UTC), 1) == datetime(2028, 2, 29, tzinfo=UTC)
    assert months_ago(datetime(2026, 9, 21, tzinfo=UTC), 36) == datetime(2023, 9, 21, tzinfo=UTC)
    assert months_ago(datetime(2026, 1, 15, tzinfo=UTC), 2) == datetime(2025, 11, 15, tzinfo=UTC)


def test_stats_older_than_36_months_are_purged_and_newer_kept() -> None:
    with _session() as session:
        channel = _channel(session, NOW)
        video = _video(session, channel, NOW)
        _observation(session, video, months_ago(NOW, 36) - timedelta(days=1))
        _observation(session, video, months_ago(NOW, 36) + timedelta(days=1))
        session.add(ChannelStats(channel_id=channel.id, observed_at=NOW - timedelta(days=1200), subscribers=1))
        session.add(ChannelStats(channel_id=channel.id, observed_at=NOW - timedelta(days=10), subscribers=2))
        session.add(IntelligenceSnapshotRecord(video_id=video.id, generated_at=NOW - timedelta(days=1200), view_json="{}", contributions_json="{}"))
        session.add(IntelligenceSnapshotRecord(video_id=video.id, generated_at=NOW - timedelta(days=5), view_json="{}", contributions_json="{}"))
        session.commit()

        result = run_retention(session, config=RetentionConfig(), now=NOW)

        assert (result.observations_deleted, result.channel_stats_deleted, result.snapshots_deleted) == (1, 1, 1)
        assert session.query(Observation).count() == 1
        assert session.query(ChannelStats).count() == 1
        assert session.query(IntelligenceSnapshotRecord).count() == 1


def test_stale_api_data_is_scrubbed_but_statistics_and_ids_are_kept() -> None:
    stale = NOW - timedelta(days=MAX_API_DATA_DAYS + 1)
    fresh = NOW - timedelta(days=MAX_API_DATA_DAYS - 1)
    with _session() as session:
        old_channel = _channel(session, stale)
        new_channel = _channel(session, fresh)
        old_video = _video(session, old_channel, stale, "old")
        new_video = _video(session, new_channel, fresh, "new")
        _observation(session, old_video, NOW - timedelta(days=40))
        session.commit()

        result = run_retention(session, config=RetentionConfig(), now=NOW)

        assert (result.videos_scrubbed, result.channels_scrubbed) == (1, 1)
        session.refresh(old_video)
        session.refresh(new_video)
        session.refresh(old_channel)
        session.refresh(new_channel)
        assert old_video.title == TITLE_PLACEHOLDER
        assert old_video.thumbnail_url is None and old_video.category_id is None
        assert old_video.youtube_video_id == "old"
        assert old_video.topic == "politics"
        assert new_video.title == "Real title" and new_video.thumbnail_url is not None
        assert old_channel.avatar_url is None and old_channel.handle is None
        assert old_channel.name == "News One"
        assert new_channel.avatar_url is not None
        assert session.query(Observation).count() == 1


def test_missing_refresh_timestamp_counts_as_stale() -> None:
    with _session() as session:
        channel = _channel(session, None)
        video = _video(session, channel, None)
        video.api_refreshed_at = None
        channel.api_refreshed_at = None
        session.commit()
        result = run_retention(session, config=RetentionConfig(), now=NOW)
        assert (result.videos_scrubbed, result.channels_scrubbed) == (1, 1)


def test_retention_is_idempotent() -> None:
    stale = NOW - timedelta(days=90)
    with _session() as session:
        channel = _channel(session, stale)
        video = _video(session, channel, stale)
        _observation(session, video, NOW - timedelta(days=1500))
        session.commit()
        first = run_retention(session, config=RetentionConfig(), now=NOW)
        second = run_retention(session, config=RetentionConfig(), now=NOW)
        assert first.changed is True
        assert second.changed is False


def test_dry_run_counts_but_changes_nothing() -> None:
    stale = NOW - timedelta(days=90)
    with _session() as session:
        channel = _channel(session, stale)
        video = _video(session, channel, stale)
        _observation(session, video, NOW - timedelta(days=1500))
        session.commit()

        result = run_retention(session, config=RetentionConfig(dry_run=True), now=NOW)

        assert result.dry_run is True
        assert (result.observations_deleted, result.videos_scrubbed, result.channels_scrubbed) == (1, 1, 1)
        assert session.query(Observation).count() == 1
        session.refresh(video)
        session.refresh(channel)
        assert video.title == "Real title"
        assert channel.avatar_url is not None

        applied = run_retention(session, config=RetentionConfig(), now=NOW, dry_run=False)
        assert applied.dry_run is False and applied.observations_deleted == 1


def test_disabled_retention_does_nothing() -> None:
    with _session() as session:
        channel = _channel(session, NOW - timedelta(days=90))
        _video(session, channel, NOW - timedelta(days=90))
        session.commit()
        result = run_retention(session, config=RetentionConfig(enabled=False), now=NOW)
        assert result.enabled is False and result.changed is False
        assert session.query(Video).one().title == "Real title"


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "", "  ", "3.5", "999", "37", "1000000"])
def test_config_never_exceeds_policy_limits(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("STAXIS_RETENTION_STATS_MONTHS", raw)
    monkeypatch.setenv("STAXIS_RETENTION_API_DATA_DAYS", raw)
    config = RetentionConfig.from_env()
    assert 1 <= config.stats_months <= MAX_STATS_MONTHS
    assert 1 <= config.api_data_days <= MAX_API_DATA_DAYS
    assert config.stats_months == MAX_STATS_MONTHS
    assert config.api_data_days == MAX_API_DATA_DAYS


def test_config_accepts_stricter_valid_limits_and_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAXIS_RETENTION_STATS_MONTHS", "12")
    monkeypatch.setenv("STAXIS_RETENTION_API_DATA_DAYS", "7")
    monkeypatch.setenv("STAXIS_RETENTION_DRY_RUN", "true")
    monkeypatch.setenv("STAXIS_RETENTION_ENABLED", "maybe")
    config = RetentionConfig.from_env()
    assert (config.stats_months, config.api_data_days) == (12, 7)
    assert config.dry_run is True
    assert config.enabled is True


def test_run_if_due_never_raises_and_is_throttled(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def boom(session, **kwargs):
        calls.append(1)
        raise RuntimeError("db down")

    monkeypatch.setattr(retention, "run_retention", boom)
    monkeypatch.setattr(retention, "_LAST_RUN", None)
    with _session() as session:
        assert run_retention_if_due(session) is None
        assert run_retention_if_due(session) is None
    assert calls == [1]


def test_recollected_video_gets_its_metadata_back_and_a_fresh_timestamp() -> None:
    stale = NOW - timedelta(days=90)
    with _session() as session:
        channel = _channel(session, stale)
        video = _video(session, channel, stale, "video1")
        session.commit()
        run_retention(session, config=RetentionConfig(), now=NOW)
        session.refresh(video)
        assert video.title == TITLE_PLACEHOLDER

        save_observations(
            session=session,
            channel_name="News One",
            channel_youtube_id=channel.youtube_channel_id,
            network="n",
            language="en",
            observations=[VideoObservation(
                video_id="video1", channel_id=channel.youtube_channel_id, observed_at=NOW, title="Fresh title",
                published_at=None, view_count=5, like_count=1, comment_count=0, concurrent_viewers=None,
                is_live=False, classification="VOD", live_started_at=None, live_ended_at=None,
                thumbnail_url="https://img/new.jpg", category_id="25",
            )],
            avatar_url="https://img/new-avatar.png",
            handle="@news",
        )
        session.refresh(video)
        session.refresh(channel)
        assert video.title == "Fresh title"
        assert video.thumbnail_url == "https://img/new.jpg"
        assert video.api_refreshed_at is not None
        assert channel.avatar_url == "https://img/new-avatar.png"
        assert channel.api_refreshed_at is not None
        stamped = video.api_refreshed_at.replace(tzinfo=UTC) if video.api_refreshed_at.tzinfo is None else video.api_refreshed_at
        assert stamped > stale


def test_existing_database_gets_refresh_column_backfilled_once(tmp_path) -> None:
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE stx_users (id INTEGER PRIMARY KEY, email TEXT, password_hash TEXT, plan TEXT, is_admin BOOLEAN, active BOOLEAN, created_at DATETIME);
        CREATE TABLE stx_channels (id INTEGER PRIMARY KEY, youtube_channel_id TEXT UNIQUE, name TEXT, network TEXT, language TEXT, region TEXT, active BOOLEAN, avatar_url TEXT, handle TEXT);
        CREATE TABLE stx_videos (id INTEGER PRIMARY KEY, youtube_video_id TEXT UNIQUE, channel_id INTEGER, title TEXT, published_at TEXT, thumbnail_url TEXT, category_id TEXT, topic TEXT);
        INSERT INTO stx_channels (id, youtube_channel_id, name, network, language, region, active, avatar_url, handle) VALUES (1, 'UC1', 'N', 'n', 'en', 'r', 1, 'a', '@h');
        INSERT INTO stx_videos (id, youtube_video_id, channel_id, title, thumbnail_url, category_id) VALUES (1, 'v1', 1, 'Old title', 't', '25');
        """
    )
    connection.commit()
    connection.close()

    engine = create_database(f"sqlite:///{path}")
    with engine.connect() as conn:
        video_stamp = conn.execute(text("SELECT api_refreshed_at FROM stx_videos WHERE id=1")).scalar_one()
        channel_stamp = conn.execute(text("SELECT api_refreshed_at FROM stx_channels WHERE id=1")).scalar_one()
    assert video_stamp is not None and channel_stamp is not None

    with Session(engine) as session:
        result = run_retention(session, config=RetentionConfig(), now=datetime.now(UTC))
        assert result.videos_scrubbed == 0 and result.channels_scrubbed == 0
    create_database(f"sqlite:///{path}")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT api_refreshed_at FROM stx_videos WHERE id=1")).scalar_one() == video_stamp
