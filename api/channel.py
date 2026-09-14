"""Read-only channel-level intelligence API accessors."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

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


def channel_intelligence_comparison(
    session: Session,
    channel_id: int,
    *,
    as_of: datetime | None = None,
    periods: tuple[tuple[str, int], ...] = (
        ("last_3_weeks", 21),
        ("last_1_month", 30),
        ("last_1_year", 365),
    ),
) -> dict[str, Any] | None:
    """Compare channel STX intelligence at real historical observation points.

    Each period compares the latest persisted snapshot available at ``as_of`` with
    the latest snapshot available exactly ``days`` earlier. Missing history stays
    missing; no values are inferred or backfilled.
    """
    channel = session.get(Channel, channel_id)
    if channel is None:
        return None
    if as_of is None:
        as_of = datetime.now(UTC)
    as_of = _utc(as_of)

    records = list(
        session.execute(
            select(IntelligenceSnapshotRecord, Video)
            .join(Video, Video.id == IntelligenceSnapshotRecord.video_id)
            .where(Video.channel_id == channel_id)
            .order_by(IntelligenceSnapshotRecord.generated_at.desc())
        ).all()
    )

    current = _aggregate_records(_latest_records_as_of(records, as_of))
    comparisons: dict[str, Any] = {}
    for name, days in periods:
        baseline_at = as_of - timedelta(days=days)
        baseline = _aggregate_records(_latest_records_as_of(records, baseline_at))
        comparisons[name] = {
            "period_days": days,
            "as_of": as_of.isoformat(),
            "baseline_at": baseline_at.isoformat(),
            "current": current,
            "baseline": baseline,
            "change": _comparison_change(current, baseline),
            "contribution_changes": _contribution_changes(
                _latest_records_as_of(records, as_of),
                _latest_records_as_of(records, baseline_at),
            ),
        }

    return {
        "channel_id": channel.id,
        "youtube_channel_id": channel.youtube_channel_id,
        "name": channel.name,
        "as_of": as_of.isoformat(),
        "comparisons": comparisons,
    }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _latest_records_as_of(
    records: Iterable[tuple[IntelligenceSnapshotRecord, Video]],
    cutoff: datetime,
) -> list[tuple[IntelligenceSnapshotRecord, Video]]:
    latest: dict[int, tuple[IntelligenceSnapshotRecord, Video]] = {}
    for record, video in records:
        generated_at = _utc(record.generated_at)
        if generated_at <= cutoff and video.id not in latest:
            latest[video.id] = (record, video)
    return list(latest.values())


def _aggregate_records(
    records: Iterable[tuple[IntelligenceSnapshotRecord, Video]],
) -> dict[str, Any] | None:
    rows = list(records)
    scored = [row for row in rows if row[0].score is not None]
    if not scored:
        return None

    weights = [max(float(record.confidence), 0.0) for record, _ in scored]
    total_weight = sum(weights)
    if total_weight > 0:
        score = sum(float(record.score) * weight for (record, _), weight in zip(scored, weights)) / total_weight
    else:
        score = sum(float(record.score) for record, _ in scored) / len(scored)

    return {
        "score": round(score, 4),
        "confidence": round(sum(float(record.confidence) for record, _ in scored) / len(scored), 4),
        "available_signals": round(sum(record.available_signals for record, _ in scored) / len(scored), 4),
        "video_count": len(scored),
    }


def _comparison_change(current: dict[str, Any] | None, baseline: dict[str, Any] | None) -> dict[str, Any]:
    if current is None or baseline is None:
        return {"score_delta": None, "score_percent_change": None, "sufficient_data": False}
    delta = current["score"] - baseline["score"]
    percent = (delta / baseline["score"] * 100) if baseline["score"] != 0 else None
    return {
        "score_delta": round(delta, 4),
        "score_percent_change": round(percent, 4) if percent is not None else None,
        "sufficient_data": True,
    }


def _contribution_changes(
    current_records: Iterable[tuple[IntelligenceSnapshotRecord, Video]],
    baseline_records: Iterable[tuple[IntelligenceSnapshotRecord, Video]],
) -> list[dict[str, Any]]:
    current = _mean_contributions(current_records)
    baseline = _mean_contributions(baseline_records)
    names = sorted(set(current) | set(baseline))
    changes = []
    for name in names:
        current_value = current.get(name)
        baseline_value = baseline.get(name)
        if current_value is None or baseline_value is None:
            continue
        changes.append({
            "name": name,
            "current": round(current_value, 4),
            "baseline": round(baseline_value, 4),
            "delta": round(current_value - baseline_value, 4),
        })
    return sorted(changes, key=lambda item: abs(item["delta"]), reverse=True)


def _mean_contributions(
    records: Iterable[tuple[IntelligenceSnapshotRecord, Video]],
) -> dict[str, float]:
    values: dict[str, list[float]] = {}
    for record, _ in records:
        try:
            payload = json.loads(record.contributions_json)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, list):
            continue
        for item in payload:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            contribution = item.get("contribution")
            if isinstance(contribution, (int, float)):
                values.setdefault(item["name"], []).append(float(contribution))
    return {name: sum(items) / len(items) for name, items in values.items() if items}
