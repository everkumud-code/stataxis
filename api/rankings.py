"""Read-only ranking accessors over persisted STX intelligence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from collector.storage import Channel, Video
from metrics.persistence import IntelligenceSnapshotRecord


def top_channel_videos(session: Session, channel_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """Return latest snapshot per video, ranked by score then confidence.

    No observations or intelligence records are modified.
    """
    if channel_id <= 0 or limit < 1:
        return []
    stmt = (
        select(IntelligenceSnapshotRecord, Video)
        .join(Video, Video.id == IntelligenceSnapshotRecord.video_id)
        .join(Channel, Channel.id == Video.channel_id)
        .where(Channel.id == channel_id)
        .order_by(IntelligenceSnapshotRecord.generated_at.desc())
    )
    latest: dict[int, tuple[IntelligenceSnapshotRecord, Video]] = {}
    for record, video in session.execute(stmt).all():
        latest.setdefault(video.id, (record, video))
    ranked = sorted(
        latest.values(),
        key=lambda pair: (
            pair[0].score is not None,
            pair[0].score if pair[0].score is not None else float("-inf"),
            pair[0].confidence,
            pair[0].generated_at,
        ),
        reverse=True,
    )
    return [
        {
            "video_id": video.id,
            "youtube_video_id": video.youtube_video_id,
            "title": video.title,
            "score": record.score,
            "confidence": record.confidence,
            "available_signals": record.available_signals,
            "generated_at": record.generated_at.isoformat(),
        }
        for record, video in ranked[:limit]
    ]
