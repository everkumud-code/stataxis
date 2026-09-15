"""Durable persistence for explainable STX intelligence snapshots."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, Session, mapped_column

from collector.storage import Base, Observation
from metrics.persisted import _utc, build_persisted_video_snapshot


class IntelligenceSnapshotRecord(Base):
    __tablename__ = "stx_intelligence_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("stx_videos.id"), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    available_signals: Mapped[int] = mapped_column(Integer, default=0)
    view_json: Mapped[str] = mapped_column(Text)
    contributions_json: Mapped[str] = mapped_column(Text)


def persist_video_intelligence(session: Session, video_id: int, *, limit: int = 25) -> IntelligenceSnapshotRecord:
    """Build and persist one deterministic, traceable intelligence snapshot."""
    snapshot = build_persisted_video_snapshot(session, video_id, limit=limit)
    intelligence = snapshot.intelligence
    rows = session.query(Observation.observed_at).filter(Observation.video_id == video_id).order_by(Observation.observed_at.desc()).limit(limit).all()
    timestamps = [_utc(row[0]) for row in rows]
    newest = max(timestamps) if timestamps else None
    oldest = min(timestamps) if timestamps else None
    window_seconds = (newest - oldest).total_seconds() if newest is not None and oldest is not None else None
    record = IntelligenceSnapshotRecord(
        video_id=video_id,
        generated_at=datetime.now(UTC),
        score=intelligence.index.score,
        confidence=intelligence.index.confidence,
        available_signals=intelligence.index.available_signals,
        view_json=json.dumps({
            "score": intelligence.index.score,
            "confidence": intelligence.view.confidence,
            "signals": [{"name": signal.name, "direction": signal.direction, "strength": signal.strength} for signal in intelligence.view.signals],
            "data": list(intelligence.view.data),
            "analysis": list(intelligence.view.analysis),
            "view": intelligence.view.view,
            "measurement_provenance": {"observation_count": len(timestamps), "oldest_observation": oldest.isoformat() if oldest else None, "newest_observation": newest.isoformat() if newest else None, "window_seconds": window_seconds},
        }, sort_keys=True),
        contributions_json=json.dumps([{"name": item.name, "value": item.value, "contribution": item.weighted_contribution, "share_of_score": item.share_of_score} for item in snapshot.contributions], sort_keys=True),
    )
    session.add(record)
    session.commit()
    return record


def persist_intelligence_snapshot(session: Session, video_id: int, *, limit: int = 25) -> IntelligenceSnapshotRecord:
    """Backward-compatible name for the canonical persistence operation."""
    return persist_video_intelligence(session, video_id, limit=limit)
