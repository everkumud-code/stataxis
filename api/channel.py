"""Read-only channel-level intelligence API accessors."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from collector.storage import Channel, Observation, Video
from metrics.persistence import IntelligenceSnapshotRecord
from metrics.eligibility import analysis_observation_clause


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


def channel_view_series(
    session: Session,
    channel_id: int,
    *,
    as_of: datetime | None = None,
    days: int = 30,
    max_points: int = 180,
) -> dict[str, Any] | None:
    """Return timestamped observed cumulative view-count movement for a channel."""
    channel = session.get(Channel, channel_id)
    if channel is None:
        return None
    if as_of is None:
        as_of = datetime.now(UTC)
    as_of = _utc(as_of)
    days = max(1, min(int(days), 365))
    max_points = max(12, min(int(max_points), 500))
    start_at = as_of - timedelta(days=days)

    rows = session.execute(
        select(Observation.observed_at, Observation.view_count)
        .where(
            Observation.channel_id == channel_id,
            Observation.observed_at >= start_at,
            Observation.observed_at <= as_of,
            Observation.view_count.is_not(None),
            analysis_observation_clause(),
        )
        .order_by(Observation.observed_at.asc(), Observation.id.asc())
    ).all()

    if not rows:
        return {
            "channel_id": channel.id,
            "name": channel.name,
            "metric": "view_count",
            "as_of": as_of.isoformat(),
            "start_at": start_at.isoformat(),
            "points": [],
        }

    span_seconds = max((as_of - start_at).total_seconds(), 1)
    bucket_seconds = max(3600, int(span_seconds / max_points))
    buckets: dict[int, tuple[datetime, int]] = {}
    for observed_at, view_count in rows:
        timestamp = _utc(observed_at)
        bucket = int((timestamp - start_at).total_seconds() // bucket_seconds)
        existing = buckets.get(bucket)
        if existing is None or timestamp >= existing[0]:
            buckets[bucket] = (timestamp, int(view_count))

    points = [
        {"observed_at": timestamp.isoformat(), "value": value}
        for timestamp, value in sorted(buckets.values(), key=lambda item: item[0])
    ]
    return {
        "channel_id": channel.id,
        "name": channel.name,
        "metric": "view_count",
        "as_of": as_of.isoformat(),
        "start_at": start_at.isoformat(),
        "bucket_seconds": bucket_seconds,
        "points": points,
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
    """Compare channel STX intelligence at real historical snapshot points."""
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

    current_records = _latest_records_as_of(records, as_of)
    current = _aggregate_records(current_records)
    comparisons: dict[str, Any] = {}
    for name, days in periods:
        baseline_at = as_of - timedelta(days=days)
        baseline_records = _latest_records_as_of(records, baseline_at)
        baseline = _aggregate_records(baseline_records)
        comparisons[name] = {
            "period_days": days,
            "as_of": as_of.isoformat(),
            "baseline_at": baseline_at.isoformat(),
            "current": current,
            "baseline": baseline,
            "change": _comparison_change(current, baseline),
            "contribution_changes": _contribution_changes(current_records, baseline_records),
        }

    return {
        "channel_id": channel.id,
        "youtube_channel_id": channel.youtube_channel_id,
        "name": channel.name,
        "as_of": as_of.isoformat(),
        "comparisons": comparisons,
    }


def compare_channels(
    session: Session,
    channel_ids: Iterable[int],
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Build a ranked multi-channel STX report from persisted intelligence.

    This composes the existing historical comparison for each requested channel,
    preserving missing periods and ranking only channels with a current score.
    """
    ids = list(dict.fromkeys(int(channel_id) for channel_id in channel_ids))
    if not ids:
        return {"as_of": _utc(as_of or datetime.now(UTC)).isoformat(), "channels": []}
    if len(ids) > 12:
        raise ValueError("a maximum of 12 channels can be compared")

    resolved_as_of = _utc(as_of or datetime.now(UTC))
    channels = []
    missing_ids = []
    for channel_id in ids:
        payload = channel_intelligence_comparison(session, channel_id, as_of=resolved_as_of)
        if payload is None:
            missing_ids.append(channel_id)
            continue
        month = payload["comparisons"]["last_1_month"]
        year = payload["comparisons"]["last_1_year"]
        channels.append({
            "channel_id": payload["channel_id"],
            "youtube_channel_id": payload["youtube_channel_id"],
            "name": payload["name"],
            "current": payload["comparisons"]["last_1_month"]["current"],
            "last_3_weeks": payload["comparisons"]["last_3_weeks"],
            "last_1_month": month,
            "last_1_year": year,
        })

    channels.sort(key=lambda item: (
        item["current"] is not None,
        item["current"]["score"] if item["current"] else float("-inf"),
        item["current"]["confidence"] if item["current"] else float("-inf"),
    ), reverse=True)
    for rank, item in enumerate(channels, start=1):
        item["rank"] = rank

    return {
        "as_of": resolved_as_of.isoformat(),
        "channels": channels,
        "missing_channel_ids": missing_ids,
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
