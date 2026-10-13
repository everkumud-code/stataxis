"""Read-only integrity checks for persisted StatAxis measurement data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
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
    """Audit relational and measurement invariants without modifying data.

    The database does the looking (anti-joins, filters, one window function); only the lines that break a rule come back. Loading every observation into Python to check it
    took about 40 seconds for half a million rows.
    """
    resolved_as_of = _utc(as_of or datetime.now(UTC))
    check_future_timestamps = as_of is None
    issues: list[IntegrityIssue] = []

    checked_channels = int(session.execute(select(func.count()).select_from(Channel)).scalar_one())
    checked_videos = int(session.execute(select(func.count()).select_from(Video)).scalar_one())
    checked_observations = int(session.execute(select(func.count()).select_from(Observation)).scalar_one())
    runs = session.execute(select(CollectionRun)).scalars().all()

    for video_id, channel_id in session.execute(select(Video.id, Video.channel_id).where(~Video.channel_id.in_(select(Channel.id))).order_by(Video.id)):
        issues.append(IntegrityIssue("orphan_video_channel", f"video {video_id} references missing channel {channel_id}"))

    for oid, video_id in session.execute(select(Observation.id, Observation.video_id).where(~Observation.video_id.in_(select(Video.id))).order_by(Observation.id)):
        issues.append(IntegrityIssue("orphan_observation_video", f"observation {oid} references missing video {video_id}"))
    for (oid,) in session.execute(select(Observation.id).join(Video, Video.id == Observation.video_id).where(Observation.channel_id != Video.channel_id).order_by(Observation.id)):
        issues.append(IntegrityIssue("observation_channel_mismatch", f"observation {oid} channel does not match its video"))
    for column, code, what in ((Observation.view_count, "negative_view_count", "views"), (Observation.like_count, "negative_like_count", "likes"),
                               (Observation.comment_count, "negative_comment_count", "comments"), (Observation.concurrent_viewers, "negative_concurrent_viewers", "concurrent viewers")):
        for (oid,) in session.execute(select(Observation.id).where(column < 0).order_by(Observation.id)):
            issues.append(IntegrityIssue(code, f"observation {oid} has negative {what}"))
    if check_future_timestamps:
        for (oid,) in session.execute(select(Observation.id).where(Observation.observed_at > resolved_as_of).order_by(Observation.id)):
            issues.append(IntegrityIssue("future_observation", f"observation {oid} is after the audit cutoff"))

    previous_views = func.lag(Observation.view_count).over(partition_by=Observation.video_id, order_by=(Observation.observed_at, Observation.id))
    steps = select(Observation.video_id.label("video_id"), Observation.view_count.label("views"), previous_views.label("previous_views"), Observation.observed_at.label("at")).subquery()
    for video_id, previous, views in session.execute(select(steps.c.video_id, steps.c.previous_views, steps.c.views).where(steps.c.previous_views.is_not(None), steps.c.views.is_not(None), steps.c.views < steps.c.previous_views).order_by(steps.c.video_id, steps.c.at)):
        issues.append(IntegrityIssue("view_count_regression", f"video {video_id} view count fell from {previous} to {views}"))

    valid_run_statuses = {"running", "success", "partial", "failed"}
    for run in runs:
        if run.status not in valid_run_statuses:
            issues.append(IntegrityIssue("invalid_run_status", f"collection run {run.id} has invalid status {run.status!r}"))
        if run.finished_at is not None and _utc(run.finished_at) < _utc(run.started_at):
            issues.append(IntegrityIssue("invalid_run_timing", f"collection run {run.id} finishes before it starts"))
        if run.channels_attempted < 0 or run.videos_observed < 0:
            issues.append(IntegrityIssue("negative_run_counts", f"collection run {run.id} has negative counters"))
        if check_future_timestamps and _utc(run.started_at) > resolved_as_of:
            issues.append(IntegrityIssue("future_collection_run", f"collection run {run.id} starts after the audit cutoff"))

    return IntegrityReport(
        ok=not issues,
        checked_channels=checked_channels,
        checked_videos=checked_videos,
        checked_observations=checked_observations,
        checked_collection_runs=len(runs),
        issues=tuple(issues),
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
