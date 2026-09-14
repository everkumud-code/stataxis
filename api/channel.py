"""Read-only channel-level intelligence API accessors."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from collector.storage import Channel, Video
from metrics.persistence import IntelligenceSnapshotRecord


def channel_intelligence_overview(session: Session, channel_id: int) -> dict[str, Any] | None:
    """Return latest explainable intelligence for each video in a channel."""
    channel = session.get(Channel, channel_id)
    if channel is None:
        return None

    stmt = (
        select(IntelligenceSnapshotRecord, Video)
        .join(Video, Video.id == IntelligenceSnapshotRecord.video_id)
        .where(Video.channel_id == channel_id)
        .order_by(IntelligenceSnapshotRecord.generated_at.desc())
    )
    latest: dict[int, tuple[IntelligenceSnapshotRecord, Video]] = {}
    for record, video in session.execute(stmt):
        latest.setdefault(video.id, (record, video))

    items = []
    for record, video in latest.values():
        items.append({
            "video_id": video.id,
            "youtube_video_id": video.youtube_video_id,
            "title": video.title,
            "score": record.score,
            "confidence": record.confidence,
            "available_signals": record.available_signals,
            "generated_at": record.generated_at.isoformat(),
        })
    items.sort(key=lambda item: (
        item["score"] is not None,
        item["score"] if item["score"] is not None else float("-inf"),
        item["confidence"],
    ), reverse=True)
    return {
        "channel_id": channel.id,
        "youtube_channel_id": channel.youtube_channel_id,
        "name": channel.name,
        "videos": items,
    }
