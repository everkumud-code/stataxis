"""Stored-data-only channel dashboard metrics and topic distributions."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from collector.storage import Channel, ChannelStats, Observation, Video
from metrics.engine import ObservationPoint
from metrics.pipeline import build_intelligence_snapshot
from metrics.timeseries import compare_metric


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _latest_stats(session: Session, channel_id: int, at: datetime | None = None) -> ChannelStats | None:
    stmt = select(ChannelStats).where(ChannelStats.channel_id == channel_id)
    if at is not None:
        stmt = stmt.where(ChannelStats.observed_at <= at)
    return session.scalars(stmt.order_by(ChannelStats.observed_at.desc())).first()


def _latest_observations(session: Session, channel_id: int) -> list[Observation]:
    rows = session.scalars(
        select(Observation)
        .where(Observation.channel_id == channel_id)
        .order_by(Observation.observed_at.desc(), Observation.id.desc())
    ).all()
    latest: dict[int, Observation] = {}
    for row in rows:
        latest.setdefault(row.video_id, row)
    return list(latest.values())


def _reasoned(value: Any, reason: str | None = None) -> dict[str, Any]:
    return {"value": value, "reason": reason}


def channel_overview(
    session: Session,
    channel_id: int,
    *,
    as_of: datetime | None = None,
    window_days: int = 30,
) -> dict[str, Any] | None:
    channel = session.get(Channel, channel_id)
    if channel is None:
        return None
    now = _utc(as_of or datetime.now(UTC))
    window_start = now - timedelta(days=max(1, min(window_days, 365)))
    current = _latest_stats(session, channel_id, now)
    baseline = _latest_stats(session, channel_id, now - timedelta(days=30))
    latest_videos = _latest_observations(session, channel_id)
    video_ids = [row.video_id for row in latest_videos]
    videos = {video.id: video for video in session.scalars(select(Video).where(Video.id.in_(video_ids))).all()} if video_ids else {}
    published = []
    for video in videos.values():
        if not video.published_at:
            continue
        try:
            published_at = _utc(datetime.fromisoformat(video.published_at.replace("Z", "+00:00")))
        except ValueError:
            continue
        if window_start <= published_at <= now:
            published.append(video)

    views = [row.view_count for row in latest_videos if row.view_count is not None]
    engagements = [
        (row.like_count or 0) + (row.comment_count or 0)
        for row in latest_videos
        if row.view_count is not None and row.like_count is not None and row.comment_count is not None
        and row.view_count > 0
    ]
    engagement_views = [
        row.view_count for row in latest_videos
        if row.view_count is not None and row.like_count is not None and row.comment_count is not None and row.view_count > 0
    ]
    avg_views = round(sum(views) / len(views), 2) if views else None
    engagement_rate = (
        round(sum(engagements) / sum(engagement_views) * 100, 4)
        if engagement_views else None
    )

    rank = None
    rank_reason = None
    if current is not None and current.subscribers is not None:
        peers = []
        for peer in session.scalars(select(Channel).where(Channel.active.is_(True), Channel.language == channel.language)).all():
            stats = _latest_stats(session, peer.id, now)
            if stats is not None and stats.subscribers is not None:
                peers.append(stats.subscribers)
        rank = 1 + sum(value > current.subscribers for value in peers)
    else:
        rank_reason = "insufficient channel statistics history"

    change = None
    change_reason = None
    if current is not None and baseline is not None and current.subscribers is not None and baseline.subscribers is not None:
        change = current.subscribers - baseline.subscribers
    else:
        change_reason = "insufficient 30-day channel statistics history"

    total_view_change = None
    total_view_change_reason = None
    if current is not None and baseline is not None and current.total_views is not None and baseline.total_views is not None:
        total_view_change = current.total_views - baseline.total_views
    else:
        total_view_change_reason = "insufficient 30-day channel statistics history"

    return {
        "channel_id": channel.id,
        "name": channel.name,
        "youtube_channel_id": channel.youtube_channel_id,
        "avatar_url": channel.avatar_url,
        "handle": channel.handle,
        "language": channel.language,
        "as_of": now.isoformat(),
        "subscribers": _reasoned(current.subscribers if current else None, "no stored channel statistics" if current is None else None),
        "subscribers_change_30d": _reasoned(change, change_reason),
        "total_views": _reasoned(current.total_views if current else None, "no stored channel statistics" if current is None else None),
        "total_views_change_30d": _reasoned(total_view_change, total_view_change_reason),
        "video_count": _reasoned(current.video_count if current else None, "no stored channel statistics" if current is None else None),
        "uploads_in_window": _reasoned(len(published), None if published else "no stored uploads in window"),
        "average_views_per_video": _reasoned(avg_views, None if avg_views is not None else "no stored view observations"),
        "engagement_rate": _reasoned(engagement_rate, None if engagement_rate is not None else "insufficient stored likes/comments/views"),
        "current_language_market_rank": _reasoned(rank, rank_reason),
    }


def channel_stx_trend(
    session: Session,
    channel_id: int,
    *,
    days: int = 30,
    as_of: datetime | None = None,
) -> dict[str, Any] | None:
    """Compute one daily STX value from observations persisted for the channel."""
    channel = session.get(Channel, channel_id)
    if channel is None:
        return None
    now = _utc(as_of or datetime.now(UTC))
    days = max(1, min(int(days), 365))
    start = (now - timedelta(days=days - 1)).date()
    videos = session.scalars(select(Video).where(Video.channel_id == channel_id)).all()
    timeline = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        cutoff = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=UTC) - timedelta(microseconds=1)
        scores = []
        for video in videos:
            rows = session.scalars(
                select(Observation)
                .where(Observation.video_id == video.id, Observation.observed_at <= cutoff)
                .order_by(Observation.observed_at.desc(), Observation.id.desc())
                .limit(25)
            ).all()
            if len(rows) < 2:
                continue
            ordered = list(reversed(rows))
            points = [
                ObservationPoint(
                    observed_at=_utc(row.observed_at),
                    view_count=row.view_count,
                    concurrent_viewers=row.concurrent_viewers,
                    like_count=row.like_count,
                    comment_count=row.comment_count,
                )
                for row in ordered
            ]
            first, last = points[0], points[-1]
            snapshot = build_intelligence_snapshot(
                data=[video.title] if video.title else [],
                observations=points,
                audience_change=compare_metric(first.concurrent_viewers, last.concurrent_viewers),
                growth_change=compare_metric(first.view_count, last.view_count),
            )
            score = snapshot.intelligence.index.score
            if score is not None:
                scores.append(float(score))
        timeline.append({
            "date": day.isoformat(),
            "stx": round(sum(scores) / len(scores), 4) if scores else None,
            "reason": None if scores else "insufficient stored observations for daily STX",
        })
    return {"channel_id": channel_id, "days": days, "timeline": timeline}


def market_topic_distribution(
    session: Session,
    *,
    period: str = "30d",
    as_of: datetime | None = None,
) -> dict[str, Any]:
    raw = period.strip().lower()
    if raw.endswith("d"):
        window_days = int(raw[:-1] or "30")
    else:
        raise ValueError("period must use Nd format, for example 7d or 30d")
    window_days = max(1, min(window_days, 365))
    now = _utc(as_of or datetime.now(UTC))
    start = now - timedelta(days=window_days)
    rows = session.execute(
        select(Channel.id, Channel.name, Video.topic, Observation.video_id, func.max(Observation.observed_at))
        .join(Video, Video.channel_id == Channel.id)
        .join(Observation, Observation.video_id == Video.id)
        .where(Observation.observed_at >= start, Observation.observed_at <= now)
        .group_by(Channel.id, Channel.name, Video.topic, Observation.video_id)
    ).all()
    channels: dict[int, dict[str, Any]] = {}
    for channel_id, name, topic, video_id, _latest in rows:
        bucket = channels.setdefault(channel_id, {"channel_id": channel_id, "name": name, "topics": {}})
        label = topic or "Other"
        bucket["topics"][label] = bucket["topics"].get(label, 0) + 1
    for bucket in channels.values():
        total = sum(bucket["topics"].values())
        bucket["topics"] = {
            topic: {"count": count, "share": round(count / total * 100, 2)}
            for topic, count in sorted(bucket["topics"].items())
        }
        bucket["reason"] = None if total else "insufficient stored topic history"
    return {"period": period, "start_at": start.isoformat(), "end_at": now.isoformat(), "channels": list(channels.values())}
