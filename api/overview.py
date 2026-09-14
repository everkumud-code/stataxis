"""Read-only channel-level intelligence aggregation for dashboard clients."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from collector.storage import Channel, Video
from metrics.persistence import IntelligenceSnapshotRecord


def latest_channel_intelligence(session: Session, channel_id: int) -> dict[str, Any] | None:
    """Return latest intelligence per video for a channel, newest first."""
    if channel_id <= 0:
        return None

    stmt = (
        select(IntelligenceSnapshotRecord, Video)
        .join(Video, Video.id == IntelligenceSnapshotRecord.video_id)
        .join(Channel, Channel.id == Video.channel_id)
        .where(Channel.id == channel_id)
        .order_by(
            IntelligenceSnapshotRecord.generated_at.desc(),
            Video.id.asc(),
        )
    )
    rows = session.execute(stmt).all()
    if not rows:
        return None

    latest_by_video: dict[int, tuple[IntelligenceSnapshotRecord, Video]] = {}
    for record, video in rows:
        latest_by_video.setdefault(video.id, (record, video))

    items = []
    for record, video in latest_by_video.values():
        items.append(
            {
                "video_id": video.id,
                "youtube_video_id": video.youtube_video_id,
                "title": video.title,
                "generated_at": record.generated_at.isoformat(),
                "score": record.score,
                "confidence": record.confidence,
                "available_signals": record.available_signals,
                "view": record.view_json,
                "contributions": record.contributions_json,
            }
        )

    items.sort(key=lambda item: item["generated_at"], reverse=True)
    return {"channel_id": channel_id, "videos": items}
