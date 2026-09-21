from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from collector.retention import DERIVED_METRIC_NOTICE, run_retention
from collector.storage import Base, Channel, ChannelStats, Observation, Video
from metrics.persistence import IntelligenceSnapshotRecord


NOW = datetime(2026, 9, 21, 8, 0, tzinfo=UTC)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _seed(session: Session, observed_at: datetime, *, active: bool = True, metadata_at: datetime | None = None, suffix: str = ""):
    channel = Channel(
        youtube_channel_id="UC-test" + suffix,
        name="Test Channel",
        active=active,
        avatar_url="https://img/avatar.jpg",
        handle="@test",
        youtube_refreshed_at=metadata_at or observed_at,
    )
    session.add(channel)
    session.flush()
    video = Video(
        youtube_video_id="video-test" + suffix,
        channel_id=channel.id,
        title="Test title",
        published_at="2026-01-01T00:00:00Z",
        thumbnail_url="https://img/thumb.jpg",
        category_id="25",
        topic="news",
        youtube_refreshed_at=metadata_at or observed_at,
    )
    session.add(video)
    session.flush()
    session.add(Observation(
        video_id=video.id,
        channel_id=channel.id,
        observed_at=observed_at,
        view_count=1000,
        like_count=100,
        comment_count=10,
        concurrent_viewers=50,
    ))
    session.add(ChannelStats(
        channel_id=channel.id,
        observed_at=observed_at,
        subscribers=5000,
        total_views=100000,
        video_count=10,
    ))
    session.add(IntelligenceSnapshotRecord(
        video_id=video.id,
        generated_at=observed_at,
        score=72.0,
        confidence=0.9,
        available_signals=7,
        view_json='{"data":["Test title"],"analysis":["title context"],"view":"Test title view"}',
        contributions_json='[{"name":"Audience","value":72}]',
    ))
    session.commit()
    return channel.id, video.id


def _configure(monkeypatch, months="36", days="30"):
    monkeypatch.setenv("STAXIS_RETENTION_STATISTICS_MONTHS", months)
    monkeypatch.setenv("STAXIS_RETENTION_METADATA_DAYS", days)


def test_36_month_statistics_and_derived_snapshot_purge(monkeypatch):
    _configure(monkeypatch)
    engine = _db()
    old = NOW.replace(year=2023, month=9, day=20)
    boundary = NOW.replace(year=2023, month=9, day=21)
    with Session(engine) as session:
        channel_id, video_id = _seed(session, old)
        channel = session.get(Channel, channel_id)
        video = session.get(Video, video_id)
        assert channel and video
        session.add(Observation(video_id=video_id, channel_id=channel_id, observed_at=boundary, view_count=2))
        session.add(ChannelStats(channel_id=channel_id, observed_at=boundary, subscribers=2))
        session.add(IntelligenceSnapshotRecord(
            video_id=video_id, generated_at=boundary, score=1, confidence=1,
            available_signals=1, view_json="{}", contributions_json="[]",
        ))
        session.commit()
        result = run_retention(session, now=NOW)
        assert result.statistics_deleted == 3
        assert session.scalar(select(Observation).where(Observation.observed_at == old)) is None
        assert session.scalar(select(ChannelStats).where(ChannelStats.observed_at == old)) is None
        assert session.scalar(select(IntelligenceSnapshotRecord).where(IntelligenceSnapshotRecord.generated_at == old)) is None
        assert session.scalar(select(Observation).where(Observation.observed_at == boundary)) is not None
        assert session.scalar(select(ChannelStats).where(ChannelStats.observed_at == boundary)) is not None


def test_30_day_metadata_is_cleared_and_refreshed_data_survives(monkeypatch):
    _configure(monkeypatch)
    engine = _db()
    with Session(engine) as session:
        _, stale_video_id = _seed(session, NOW - timedelta(days=40), metadata_at=NOW - timedelta(days=31))
        fresh_channel_id, fresh_video_id = _seed(session, NOW - timedelta(days=40), metadata_at=NOW - timedelta(days=29), suffix="-fresh")
        # Separate the unique IDs for the second seed.
        fresh_channel = session.get(Channel, fresh_channel_id)
        fresh_video = session.get(Video, fresh_video_id)
        assert fresh_channel and fresh_video
        session.commit()

        result = run_retention(session, now=NOW)
        assert result.metadata_cleared >= 2

        stale_video = session.get(Video, stale_video_id)
        assert stale_video
        assert stale_video.title == ""
        assert stale_video.thumbnail_url is None
        assert stale_video.published_at is None
        assert stale_video.category_id is None
        assert stale_video.topic is None
        assert stale_video.youtube_video_id == "video-test"

        assert fresh_video.title == "Test title"
        assert fresh_channel.avatar_url == "https://img/avatar.jpg"


def test_removed_channel_metadata_is_cleared_but_statistics_and_ids_remain(monkeypatch):
    _configure(monkeypatch)
    engine = _db()
    with Session(engine) as session:
        channel_id, video_id = _seed(session, NOW - timedelta(days=2), active=False)
        result = run_retention(session, covered_channel_ids=set(), now=NOW)
        assert result.removed_channel_metadata_cleared == 1
        video = session.get(Video, video_id)
        channel = session.get(Channel, channel_id)
        assert video and channel
        assert video.youtube_video_id == "video-test"
        assert video.title == ""
        assert channel.youtube_channel_id == "UC-test"
        assert session.scalar(select(Observation).where(Observation.video_id == video_id)) is not None


def test_dry_run_does_not_modify(monkeypatch):
    _configure(monkeypatch)
    engine = _db()
    with Session(engine) as session:
        _, video_id = _seed(session, NOW - timedelta(days=40), metadata_at=NOW - timedelta(days=31))
        result = run_retention(session, now=NOW, dry_run=True)
        assert result.dry_run is True
        video = session.get(Video, video_id)
        assert video and video.title == "Test title"


def test_retention_is_idempotent(monkeypatch):
    _configure(monkeypatch)
    engine = _db()
    with Session(engine) as session:
        _seed(session, NOW - timedelta(days=40), metadata_at=NOW - timedelta(days=31))
        first = run_retention(session, now=NOW)
        second = run_retention(session, now=NOW)
        assert first.metadata_cleared >= 2
        assert second.statistics_deleted == 0
        assert second.snapshots_deleted == 0
        assert second.metadata_cleared == 0


def test_missing_or_invalid_config_never_deletes(monkeypatch):
    monkeypatch.delenv("STAXIS_RETENTION_STATISTICS_MONTHS", raising=False)
    monkeypatch.delenv("STAXIS_RETENTION_METADATA_DAYS", raising=False)
    engine = _db()
    with Session(engine) as session:
        _, video_id = _seed(session, NOW - timedelta(days=40), metadata_at=NOW - timedelta(days=31))
        result = run_retention(session, now=NOW)
        assert result.enabled is False
        assert session.get(Video, video_id).title == "Test title"

    monkeypatch.setenv("STAXIS_RETENTION_STATISTICS_MONTHS", "invalid")
    monkeypatch.setenv("STAXIS_RETENTION_METADATA_DAYS", "30")
    with Session(engine) as session:
        result = run_retention(session, now=NOW)
        assert result.enabled is False


def test_derived_metric_notice_is_added_when_snapshot_metadata_is_sanitized(monkeypatch):
    _configure(monkeypatch)
    engine = _db()
    with Session(engine) as session:
        _, video_id = _seed(session, NOW - timedelta(days=31), metadata_at=NOW - timedelta(days=31))
        run_retention(session, now=NOW)
        record = session.scalar(select(IntelligenceSnapshotRecord).where(IntelligenceSnapshotRecord.video_id == video_id))
        assert record is not None
        assert DERIVED_METRIC_NOTICE in record.view_json
        assert "Test title" not in record.view_json
