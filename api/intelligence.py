"""Read-only accessors for persisted StatAxis intelligence."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from collector.storage import Video
from metrics.persistence import IntelligenceSnapshotRecord


def latest_video_intelligence(session: Session, video_id: int) -> dict[str, Any] | None:
    """Return the newest explainable intelligence snapshot for a video."""
    stmt = (
        select(IntelligenceSnapshotRecord, Video)
        .join(Video, Video.id == IntelligenceSnapshotRecord.video_id)
        .where(IntelligenceSnapshotRecord.video_id == video_id)
        .order_by(IntelligenceSnapshotRecord.generated_at.desc())
        .limit(1)
    )
    row = session.execute(stmt).first()
    if row is None:
        return None
    record, video = row
    return {
        "video_id": video.id,
        "youtube_video_id": video.youtube_video_id,
        "title": video.title,
        "generated_at": record.generated_at.isoformat(),
        "score": record.score,
        "confidence": record.confidence,
        "available_signals": record.available_signals,
        "view": json.loads(record.view_json),
        "contributions": json.loads(record.contributions_json),
    }
