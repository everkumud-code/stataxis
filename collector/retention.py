"""YouTube API retention enforcement for StatAxis.

The job intentionally requires explicit retention settings before any deletion.
Missing or invalid settings disable destructive retention actions.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from calendar import monthrange

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from collector.storage import Channel, ChannelStats, Observation, Video
from metrics.persistence import IntelligenceSnapshotRecord

logger = logging.getLogger("stataxis-retention")
DERIVED_METRIC_NOTICE = "Generated independently by StatAxis; not sourced from YouTube"


@dataclass(frozen=True)
class RetentionConfig:
    statistics_months: int
    metadata_days: int


@dataclass(frozen=True)
class RetentionResult:
    enabled: bool
    dry_run: bool
    statistics_deleted: int = 0
    snapshots_deleted: int = 0
    metadata_cleared: int = 0
    removed_channel_metadata_cleared: int = 0
    reason: str | None = None


def _parse_positive_env(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    return value if value > 0 else None


def load_retention_config() -> tuple[RetentionConfig | None, str | None]:
    months = _parse_positive_env("STAXIS_RETENTION_STATISTICS_MONTHS")
    days = _parse_positive_env("STAXIS_RETENTION_METADATA_DAYS")
    if months is None:
        return None, "STAXIS_RETENTION_STATISTICS_MONTHS is missing or invalid"
    if days is None:
        return None, "STAXIS_RETENTION_METADATA_DAYS is missing or invalid"
    return RetentionConfig(months, days), None


def subtract_calendar_months(value: datetime, months: int) -> datetime:
    total = value.year * 12 + (value.month - 1) - months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _sanitize_snapshot(record: IntelligenceSnapshotRecord) -> bool:
    try:
        payload = json.loads(record.view_json or "{}")
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    changed = False
    for key in ("data", "analysis", "view"):
        if payload.get(key):
            payload[key] = [] if key != "view" else "StatAxis View retained without expired YouTube metadata."
            changed = True
    if changed:
        payload["derived_metric_notice"] = DERIVED_METRIC_NOTICE
        record.view_json = json.dumps(payload, sort_keys=True)
    return changed


def run_retention(
    session: Session,
    *,
    covered_channel_ids: set[str] | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> RetentionResult:
    config, reason = load_retention_config()
    if config is None:
        logger.warning("retention disabled: %s", reason)
        return RetentionResult(enabled=False, dry_run=dry_run, reason=reason)

    now = _utc(now or datetime.now(UTC))
    statistics_cutoff = subtract_calendar_months(now, config.statistics_months)
    metadata_cutoff = now - timedelta(days=config.metadata_days)

    stale_observation_ids = list(
        session.scalars(
            select(Observation.id).where(Observation.observed_at < statistics_cutoff)
        )
    )
    stale_channel_stat_ids = list(
        session.scalars(
            select(ChannelStats.id).where(ChannelStats.observed_at < statistics_cutoff)
        )
    )
    stale_snapshot_ids = list(
        session.scalars(
            select(IntelligenceSnapshotRecord.id).where(
                IntelligenceSnapshotRecord.generated_at < statistics_cutoff
            )
        )
    )

    stale_videos = list(session.scalars(select(Video).where(
        Video.youtube_refreshed_at.is_(None) | (Video.youtube_refreshed_at < metadata_cutoff)
    )))
    stale_channels = list(session.scalars(select(Channel).where(
        Channel.youtube_refreshed_at.is_(None) | (Channel.youtube_refreshed_at < metadata_cutoff)
    )))
    removed_channels = []
    if covered_channel_ids is not None:
        removed_channels = list(session.scalars(select(Channel).where(
            Channel.active.is_(False)
        )))

    metadata_cleared = len(stale_videos) + len(stale_channels)
    removed_metadata_cleared = 0

    if not dry_run:
        if stale_snapshot_ids:
            session.execute(delete(IntelligenceSnapshotRecord).where(IntelligenceSnapshotRecord.id.in_(stale_snapshot_ids)))
        if stale_observation_ids:
            session.execute(delete(Observation).where(Observation.id.in_(stale_observation_ids)))
        if stale_channel_stat_ids:
            session.execute(delete(ChannelStats).where(ChannelStats.id.in_(stale_channel_stat_ids)))

        for video in stale_videos:
            video.title = ""
            video.published_at = None
            video.thumbnail_url = None
            video.category_id = None
            video.topic = None
        for channel in stale_channels:
            channel.avatar_url = None
            channel.handle = None

        for channel in removed_channels:
            removed_video_ids = list(session.scalars(
                select(Video.id).where(Video.channel_id == channel.id)
            ))
            for video_id in removed_video_ids:
                video = session.get(Video, video_id)
                if video is not None:
                    video.title = ""
                    video.published_at = None
                    video.thumbnail_url = None
                    video.category_id = None
                    video.topic = None
                    removed_metadata_cleared += 1
            channel.avatar_url = None
            channel.handle = None
            channel.youtube_refreshed_at = now

        old_metadata_snapshots = list(session.scalars(select(IntelligenceSnapshotRecord).where(
            IntelligenceSnapshotRecord.generated_at < metadata_cutoff,
            IntelligenceSnapshotRecord.generated_at >= statistics_cutoff,
        )))
        for record in old_metadata_snapshots:
            _sanitize_snapshot(record)
        session.commit()
    else:
        old_metadata_snapshots = list(session.scalars(select(IntelligenceSnapshotRecord).where(
            IntelligenceSnapshotRecord.generated_at < metadata_cutoff,
            IntelligenceSnapshotRecord.generated_at >= statistics_cutoff,
        )))
        metadata_cleared += sum(
            1 for record in old_metadata_snapshots if _snapshot_needs_sanitization(record)
        )

    logger.info(
        "retention dry_run=%s statistics_cutoff=%s metadata_cutoff=%s observations=%d channel_stats=%d snapshots=%d metadata_cleared=%d removed_channel_metadata=%d",
        dry_run, statistics_cutoff.isoformat(), metadata_cutoff.isoformat(),
        len(stale_observation_ids), len(stale_channel_stat_ids), len(stale_snapshot_ids),
        metadata_cleared, removed_metadata_cleared,
    )
    return RetentionResult(
        enabled=True,
        dry_run=dry_run,
        statistics_deleted=len(stale_observation_ids) + len(stale_channel_stat_ids),
        snapshots_deleted=len(stale_snapshot_ids),
        metadata_cleared=metadata_cleared,
        removed_channel_metadata_cleared=removed_metadata_cleared,
    )


def _snapshot_needs_sanitization(record: IntelligenceSnapshotRecord) -> bool:
    try:
        payload = json.loads(record.view_json or "{}")
    except (TypeError, ValueError):
        return True
    return any(payload.get(key) for key in ("data", "analysis", "view"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply StatAxis YouTube API retention policy")
    parser.add_argument("--dry-run", action="store_true", help="report changes without modifying the database")
    parser.add_argument("--database-url", default=None, help="database URL; defaults to DATABASE_URL")
    args = parser.parse_args()

    from collector.storage import create_database
    database_url = args.database_url or os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is not configured")
    engine = create_database(database_url)
    with Session(engine) as session:
        result = run_retention(session, dry_run=args.dry_run)
    logger.info("retention result: %s", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
