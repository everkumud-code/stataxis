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
    view_payload = _safe_object(record.view_json)
    contributions = _safe_list(record.contributions_json)
    signals = view_payload.get("signals", [])
    if not isinstance(signals, list):
        signals = []
    return {
        "video_id": video.id,
        "youtube_video_id": video.youtube_video_id,
        "title": video.title,
        "generated_at": record.generated_at.isoformat(),
        "score": record.score,
        "confidence": record.confidence,
        "available_signals": record.available_signals,
        "stx_index": {"score": record.score, "confidence": record.confidence, "available_signals": record.available_signals},
        "signals": signals,
        "data": view_payload.get("data", []),
        "analysis": view_payload.get("analysis", []),
        "view": view_payload.get("view", "No persisted StatAxis View available."),
        "stat_axis_view": view_payload,
        "signal_contributions": contributions,
        "contributions": contributions,
        "measurement_provenance": view_payload.get("measurement_provenance", {}),
    }


def _safe_object(value: str | None) -> dict[str, Any]:
    try:
        payload = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_list(value: str | None) -> list[dict[str, Any]]:
    try:
        payload = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []
