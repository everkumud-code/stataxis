"""Read-only integrity checks for persisted StatAxis measurement data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from collector.storage import Channel, CollectionRun, Observation, Video


@dataclass(frozen=True)
class IntegrityIssue:
    code: str
    message: str


@dataclass(frozen=True)
class IntegrityReport:
    ok: bool
    checked_channels: int
    checked_videos: int
    checked_observations: int
    checked_collection_runs: int
    issues: tuple[IntegrityIssue, ...]


def audit_database(session: Session, *, as_of: datetime | None = None) -> IntegrityReport:
    """Audit relational and measurement invariants without modifying data."""
    resolved_as_of = _utc(as_of or datetime.now(UTC))
    issues: list[IntegrityIssue] = []

    channels = session.execute(select(Channel)).scalars().all()
    videos = session.execute(select(Video)).scalars().all()
    observations = session.execute(select(Observation)).scalars().all()
    runs = session.execute(select(CollectionRun)).scalars().all()

    channel_ids = {channel.id for channel in channels}
    video_ids = {video.id for video in videos}
    video_channel = {video.id: video.channel_id for video in videos}

    for video in videos:
        if video.channel_id not in channel_ids:
            issues.append(IntegrityIssue("orphan_video_channel", f"video {video.id} references missing channel {video.channel_id}"))

    for observation in observations:
        if observation.video_id not in video_ids:
            issues.append(IntegrityIssue("orphan_observation_video", f"observation {observation.id} references missing video {observation.video_id}"))
        elif observation.channel_id != video_channel[observation.video_id]:
            issues.append(IntegrityIssue("observation_channel_mismatch", f"observation {observation.id} channel does not match its video"))
        if observation.view_count is not None and observation.view_count < 0:
            issues.append(IntegrityIssue("negative_view_count", f"observation {observation.id} has negative views"))
        if observation.like_count is not None and observation.like_count < 0:
            issues.append(IntegrityIssue("negative_like_count", f"observation {observation.id} has negative likes"))
        if observation.comment_count is not None and observation.comment_count < 0:
            issues.append(IntegrityIssue("negative_comment_count", f"observation {observation.id} has negative comments"))
        if observation.concurrent_viewers is not None and observation.concurrent_viewers < 0:
            issues.append(IntegrityIssue("negative_concurrent_viewers", f"observation {observation.id} has negative concurrent viewers"))
        if _utc(observation.observed_at) > resolved_as_of:
            issues.append(IntegrityIssue("future_observation", f"observation {observation.id} is after the audit cutoff"))

    valid_run_statuses = {"running", "success", "partial", "failed"}
    for run in runs:
        if run.status not in valid_run_statuses:
            issues.append(IntegrityIssue("invalid_run_status", f"collection run {run.id} has invalid status {run.status!r}"))
        if run.finished_at is not None and _utc(run.finished_at) < _utc(run.started_at):
            issues.append(IntegrityIssue("invalid_run_timing", f"collection run {run.id} finishes before it starts"))
        if run.channels_attempted < 0 or run.videos_observed < 0:
            issues.append(IntegrityIssue("negative_run_counts", f"collection run {run.id} has negative counters"))
        if _utc(run.started_at) > resolved_as_of:
            issues.append(IntegrityIssue("future_collection_run", f"collection run {run.id} starts after the audit cutoff"))

    return IntegrityReport(
        ok=not issues,
        checked_channels=len(channels),
        checked_videos=len(videos),
        checked_observations=len(observations),
        checked_collection_runs=len(runs),
        issues=tuple(issues),
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
