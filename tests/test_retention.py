from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from collector.retention import (
    MAX_API_DATA_DAYS,
    MAX_STATS_MONTHS,
    TITLE_PLACEHOLDER,
    RetentionConfig,
    months_ago,
    run_retention,
)
from collector.storage import Base, Channel, ChannelStats, Observation, Video
from metrics.persistence import IntelligenceSnapshotRecord


NOW = datetime(2026, 9, 21, 10, tzinfo=UTC)


def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed(s: Session, when: datetime, refreshed: datetime | None = None) -> tuple[int, int]:
    channel = Channel(
        youtube_channel_id="UC-test",
        name="Test Channel",
        avatar_url="avatar",
        handle="@test",
        api_refreshed_at=refreshed or when,
    )
    s.add(channel)
    s.flush()
    video = Video(
        youtube_video_id="video-test",
        channel_id=channel.id,
        title="Test title",
        thumbnail_url="thumb",
        category_id="25",
        topic="news",
        api_refreshed_at=refreshed or when,
    )
    s.add(video)
    s.flush()
    s.add(Observation(
        video_id=video.id, channel_id=channel.id, observed_at=when,
        view_count=100, like_count=10, comment_count=2, concurrent_viewers=5,
    ))
    s.add(ChannelStats(
        channel_id=channel.id, observed_at=when,
        subscribers=1000, total_views=5000, video_count=20,
    ))
    s.add(IntelligenceSnapshotRecord(
        video_id=video.id, generated_at=when, score=72.5, confidence=90,
        available_signals=7, view_json='{"view":"Positive evidence"}', contributions_json="[]",
    ))
    s.commit()
    return channel.id, video.id


def test_months_ago_is_calendar_based() -> None:
    assert months_ago(datetime(2026, 3, 31, tzinfo=UTC), 1) == datetime(2026, 2, 28, tzinfo=UTC)
    assert months_ago(datetime(2026, 9, 21, tzinfo=UTC), 36) == datetime(2023, 9, 21, tzinfo=UTC)


def test_default_limits_are_policy_maxima(monkeypatch) -> None:
    for name in ("STAXIS_RETENTION_STATS_MONTHS", "STAXIS_RETENTION_API_DATA_DAYS"):
        monkeypatch.delenv(name, raising=False)
    config = RetentionConfig.from_env()
    assert config.stats_months == MAX_STATS_MONTHS
    assert config.api_data_days == MAX_API_DATA_DAYS


def test_invalid_limits_fall_back_to_safe_maximum(monkeypatch) -> None:
    monkeypatch.setenv("STAXIS_RETENTION_STATS_MONTHS", "invalid")
    monkeypatch.setenv("STAXIS_RETENTION_API_DATA_DAYS", "999")
    config = RetentionConfig.from_env()
    assert config.stats_months == MAX_STATS_MONTHS
    assert config.api_data_days == MAX_API_DATA_DAYS


def test_36_month_statistics_and_snapshots_are_deleted() -> None:
    s = session()
    old = months_ago(NOW, 36) - timedelta(seconds=1)
    current = months_ago(NOW, 36)
    channel_id, video_id = seed(s, old)
    s.add(Observation(video_id=video_id, channel_id=channel_id, observed_at=current, view_count=1))
    s.add(ChannelStats(channel_id=channel_id, observed_at=current, subscribers=1))
    s.commit()
    result = run_retention(s, now=NOW, config=RetentionConfig())
    assert result.observations_deleted == 1
    assert result.channel_stats_deleted == 1
    assert result.snapshots_deleted == 1
    assert s.scalar(select(Observation).where(Observation.observed_at == current)) is not None
    s.close()


def test_stale_metadata_is_scrubbed_after_30_days() -> None:
    s = session()
    channel_id, video_id = seed(s, NOW - timedelta(days=31))
    result = run_retention(s, now=NOW, config=RetentionConfig())
    assert result.videos_scrubbed == 1
    assert result.channels_scrubbed == 1
    video = s.get(Video, video_id)
    channel = s.get(Channel, channel_id)
    assert video.title == TITLE_PLACEHOLDER
    assert video.thumbnail_url is None
    assert video.category_id is None
    assert video.youtube_video_id == "video-test"
    assert channel.avatar_url is None
    assert channel.handle is None
    assert channel.youtube_channel_id == "UC-test"
    s.close()


def test_fresh_metadata_survives() -> None:
    s = session()
    channel_id, video_id = seed(s, NOW - timedelta(days=31), refreshed=NOW - timedelta(days=29))
    result = run_retention(s, now=NOW, config=RetentionConfig())
    assert result.videos_scrubbed == 0
    assert result.channels_scrubbed == 0
    assert s.get(Video, video_id).title == "Test title"
    assert s.get(Channel, channel_id).avatar_url == "avatar"
    s.close()


def test_dry_run_does_not_modify() -> None:
    s = session()
    _, video_id = seed(s, NOW - timedelta(days=31))
    result = run_retention(s, now=NOW, config=RetentionConfig(dry_run=True))
    assert result.dry_run is True
    assert result.videos_scrubbed == 1
    assert s.get(Video, video_id).title == "Test title"
    s.close()


def test_idempotent_after_first_run() -> None:
    s = session()
    seed(s, NOW - timedelta(days=31))
    config = RetentionConfig()
    first = run_retention(s, now=NOW, config=config)
    second = run_retention(s, now=NOW, config=config)
    assert first.changed
    assert not second.changed
    s.close()


def test_disabled_retention_does_not_delete() -> None:
    s = session()
    _, video_id = seed(s, NOW - timedelta(days=31))
    result = run_retention(s, now=NOW, config=RetentionConfig(enabled=False))
    assert result.enabled is False
    assert s.get(Video, video_id).title == "Test title"
    s.close()
