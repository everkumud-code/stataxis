"""Data retention for YouTube API data.

Enforces the storage rules that apply to StatAxis under the YouTube API Services
Developer Policies and the derived-metrics / data-storage addendum:

* Public statistics (views, likes, comments, subscriber counts, concurrent viewers)
  and metrics derived from them are kept for at most 36 calendar months.
* Other YouTube API data (video titles, thumbnails, categories, channel avatars and
  handles) must be refreshed from the API at least every 30 calendar days. Data that
  has not been refreshed within that window is cleared. Numeric statistics and IDs
  are kept so rankings and history keep working.

Design notes
------------
* Idempotent: running it twice in a row changes nothing the second time.
* ``dry_run`` counts what would change without modifying anything.
* Limits come from environment variables but can never exceed the policy maximum,
  and invalid values fall back to the policy defaults, never to "keep forever".
* Channel display names are editorial labels set by StatAxis (registry / admin
  rename), so they are not scrubbed here.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from calendar import monthrange
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from collector.storage import Channel, ChannelStats, Observation, Video, create_database
from metrics.persistence import IntelligenceSnapshotRecord

logger = logging.getLogger("stataxis-retention")

MAX_STATS_MONTHS = 36
MAX_API_DATA_DAYS = 30
TITLE_PLACEHOLDER = "[title not retained]"

ENV_ENABLED = "STAXIS_RETENTION_ENABLED"
ENV_DRY_RUN = "STAXIS_RETENTION_DRY_RUN"
ENV_STATS_MONTHS = "STAXIS_RETENTION_STATS_MONTHS"
ENV_API_DATA_DAYS = "STAXIS_RETENTION_API_DATA_DAYS"

_FALSE = {"0", "false", "no", "off"}
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RetentionConfig:
    """Effective retention limits. Always within the policy maximums."""

    enabled: bool = True
    dry_run: bool = False
    stats_months: int = MAX_STATS_MONTHS
    api_data_days: int = MAX_API_DATA_DAYS

    @classmethod
    def from_env(cls) -> RetentionConfig:
        return cls(
            enabled=_env_flag(ENV_ENABLED, default=True),
            dry_run=_env_flag(ENV_DRY_RUN, default=False),
            stats_months=_env_limit(ENV_STATS_MONTHS, MAX_STATS_MONTHS),
            api_data_days=_env_limit(ENV_API_DATA_DAYS, MAX_API_DATA_DAYS),
        )


@dataclass(frozen=True)
class RetentionResult:
    """What a retention run deleted (or would delete when ``dry_run`` is true)."""

    dry_run: bool
    enabled: bool
    observations_deleted: int = 0
    channel_stats_deleted: int = 0
    snapshots_deleted: int = 0
    videos_scrubbed: int = 0
    channels_scrubbed: int = 0

    @property
    def changed(self) -> bool:
        return any((
            self.observations_deleted, self.channel_stats_deleted,
            self.snapshots_deleted, self.videos_scrubbed, self.channels_scrubbed,
        ))


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    logger.warning("invalid %s=%r; using default %s", name, raw, default)
    return default


def _env_limit(name: str, maximum: int) -> int:
    """Read a positive integer limit, never above the policy maximum."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return maximum
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning("invalid %s=%r; using policy maximum %d", name, raw, maximum)
        return maximum
    if value < 1:
        logger.warning("invalid %s=%d; using policy maximum %d", name, value, maximum)
        return maximum
    if value > maximum:
        logger.warning("%s=%d exceeds the policy maximum; clamped to %d", name, value, maximum)
        return maximum
    return value


def months_ago(moment: datetime, months: int) -> datetime:
    """Return ``moment`` shifted back by whole calendar months (day clamped to month end)."""
    if months < 0:
        raise ValueError("months must be non-negative")
    index = moment.year * 12 + (moment.month - 1) - months
    year, month = divmod(index, 12)
    month += 1
    day = min(moment.day, monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def _count(session: Session, model, *conditions) -> int:
    return int(session.execute(select(func.count()).select_from(model).where(*conditions)).scalar_one())


def run_retention(
    session: Session,
    *,
    config: RetentionConfig | None = None,
    now: datetime | None = None,
    dry_run: bool | None = None,
) -> RetentionResult:
    """Apply the retention rules once. Commits on success, changes nothing in dry-run."""
    config = config or RetentionConfig.from_env()
    dry = config.dry_run if dry_run is None else dry_run
    if not config.enabled:
        return RetentionResult(dry_run=dry, enabled=False)

    now = (now or datetime.now(UTC)).astimezone(UTC)
    stats_cutoff = months_ago(now, config.stats_months)
    api_cutoff = now - timedelta(days=config.api_data_days)

    stale_video = or_(Video.api_refreshed_at.is_(None), Video.api_refreshed_at < api_cutoff)
    video_has_data = or_(
        Video.title != TITLE_PLACEHOLDER,
        Video.thumbnail_url.is_not(None),
        Video.category_id.is_not(None),
    )
    stale_channel = or_(Channel.api_refreshed_at.is_(None), Channel.api_refreshed_at < api_cutoff)
    channel_has_data = or_(Channel.avatar_url.is_not(None), Channel.handle.is_not(None))

    if dry:
        result = RetentionResult(
            dry_run=True,
            enabled=True,
            observations_deleted=_count(session, Observation, Observation.observed_at < stats_cutoff),
            channel_stats_deleted=_count(session, ChannelStats, ChannelStats.observed_at < stats_cutoff),
            snapshots_deleted=_count(session, IntelligenceSnapshotRecord, IntelligenceSnapshotRecord.generated_at < stats_cutoff),
            videos_scrubbed=_count(session, Video, stale_video, video_has_data),
            channels_scrubbed=_count(session, Channel, stale_channel, channel_has_data),
        )
    else:
        bulk = {"synchronize_session": False}
        observations = session.execute(
            delete(Observation).where(Observation.observed_at < stats_cutoff), execution_options=bulk
        ).rowcount
        channel_stats = session.execute(
            delete(ChannelStats).where(ChannelStats.observed_at < stats_cutoff), execution_options=bulk
        ).rowcount
        snapshots = session.execute(
            delete(IntelligenceSnapshotRecord).where(IntelligenceSnapshotRecord.generated_at < stats_cutoff),
            execution_options=bulk,
        ).rowcount
        videos = session.execute(
            update(Video)
            .where(stale_video, video_has_data)
            .values(title=TITLE_PLACEHOLDER, thumbnail_url=None, category_id=None),
            execution_options=bulk,
        ).rowcount
        channels = session.execute(
            update(Channel).where(stale_channel, channel_has_data).values(avatar_url=None, handle=None),
            execution_options=bulk,
        ).rowcount
        session.commit()
        result = RetentionResult(
            dry_run=False,
            enabled=True,
            observations_deleted=observations or 0,
            channel_stats_deleted=channel_stats or 0,
            snapshots_deleted=snapshots or 0,
            videos_scrubbed=videos or 0,
            channels_scrubbed=channels or 0,
        )

    if result.changed:
        logger.info(
            "retention %s: observations=%d channel_stats=%d snapshots=%d videos_scrubbed=%d channels_scrubbed=%d",
            "dry-run" if result.dry_run else "applied",
            result.observations_deleted, result.channel_stats_deleted, result.snapshots_deleted,
            result.videos_scrubbed, result.channels_scrubbed,
        )
    return result


_LAST_RUN: float | None = None


def run_retention_if_due(session: Session, *, min_interval_seconds: int = 3600) -> RetentionResult | None:
    """Run retention at most once per interval per process. Never raises."""
    global _LAST_RUN
    now = time.monotonic()
    if _LAST_RUN is not None and now - _LAST_RUN < min_interval_seconds:
        return None
    _LAST_RUN = now
    try:
        return run_retention(session)
    except Exception:
        session.rollback()
        logger.exception("retention run failed")
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply StatAxis data retention rules.")
    parser.add_argument("--dry-run", action="store_true", help="count what would change without changing anything")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    database_url = os.getenv("DATABASE_URL")
    if not database_url or not database_url.strip():
        logger.error("DATABASE_URL is not configured")
        return 2
    engine = create_database(database_url)
    with Session(engine) as session:
        result = run_retention(session, dry_run=True if args.dry_run else None)
    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
