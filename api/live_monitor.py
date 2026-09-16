"""Precision live audience sampling and language-group aggregation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.access import require_capability
from api.auth import AuthIdentity
from api.auth_service import policy_for_identity
from collector.storage import Channel, Observation, save_observations
from collector.youtube.client import YouTubeClient
from collector.youtube.manual_live import ManualLiveTarget, fetch_manual_live


def sample_live_url(
    session: Session,
    identity: AuthIdentity,
    url: str,
    display_name: str,
) -> dict[str, Any]:
    """Capture exactly one current YouTube live observation for a premium user."""
    require_capability(policy_for_identity(identity), "can_evaluate_url")
    target = ManualLiveTarget.from_url(url, display_name)
    with YouTubeClient() as youtube:
        observation = fetch_manual_live(youtube, target)
        channel_meta = youtube.get_channel(observation.channel_id)
        snippet = channel_meta.get("snippet", {})
        existing = session.query(Channel).filter_by(youtube_channel_id=observation.channel_id).one_or_none()
        language = str(snippet.get("defaultLanguage") or (existing.language if existing else "unknown"))
        network = str(snippet.get("customUrl") or (existing.network if existing else "youtube"))
        channel_name = str(snippet.get("title") or (existing.name if existing else observation.channel_id))
        saved = save_observations(
            session,
            channel_name=channel_name,
            channel_youtube_id=observation.channel_id,
            network=network,
            language=language,
            observations=[observation],
        )

    return {
        "video_id": observation.video_id,
        "channel_id": observation.channel_id,
        "channel_name": channel_name,
        "display_name": observation.title,
        "observed_at": observation.observed_at.isoformat(),
        "view_count": observation.view_count,
        "concurrent_viewers": observation.concurrent_viewers,
        "is_live": observation.is_live,
        "language": language,
        "language_group": language_group(language),
        "saved": bool(saved),
    }


def live_audience_window(
    session: Session,
    *,
    start_at: datetime,
    end_at: datetime,
    language: str | None = None,
) -> dict[str, Any]:
    """Return observed live concurrent-viewer movement without interpolation."""
    start_at = _utc(start_at)
    end_at = _utc(end_at)
    if end_at <= start_at:
        raise ValueError("end_at must be after start_at")
    if end_at - start_at > timedelta(hours=24):
        raise ValueError("live audience window cannot exceed 24 hours")

    stmt = (
        select(Observation, Channel)
        .join(Channel, Channel.id == Observation.channel_id)
        .where(
            Observation.observed_at >= start_at,
            Observation.observed_at <= end_at,
            Observation.is_live.is_(True),
            Observation.concurrent_viewers.is_not(None),
            Channel.active.is_(True),
        )
        .order_by(Observation.observed_at.asc(), Observation.id.asc())
    )
    rows = list(session.execute(stmt).all())
    if language:
        target = language.strip().lower()
        rows = [row for row in rows if language_group(row[1].language).lower() == target or row[1].language.lower() == target]

    groups = {"Hindi": [], "English": [], "Regional": [], "Unknown": []}
    timeline: dict[datetime, dict[str, int]] = {}
    channel_latest: dict[int, tuple[Observation, Channel]] = {}
    channel_peaks: dict[int, int] = {}

    for observation, channel in rows:
        group = language_group(channel.language)
        groups[group].append((observation, channel))
        timestamp = _utc(observation.observed_at).replace(microsecond=0)
        bucket = timeline.setdefault(timestamp, {name: 0 for name in groups})
        bucket[group] += int(observation.concurrent_viewers or 0)
        current = channel_latest.get(channel.id)
        if current is None or _utc(observation.observed_at) >= _utc(current[0].observed_at):
            channel_latest[channel.id] = (observation, channel)
        channel_peaks[channel.id] = max(channel_peaks.get(channel.id, 0), int(observation.concurrent_viewers or 0))

    summaries: dict[str, dict[str, Any]] = {}
    for group, items in groups.items():
        values = [int(observation.concurrent_viewers or 0) for observation, _ in items]
        latest_values = [int(observation.concurrent_viewers or 0) for observation, _ in channel_latest.values() if language_group(_[1].language) == group]
        summaries[group] = {
            "channel_count": len({channel.id for _, channel in items}),
            "observations": len(items),
            "current_concurrent": sum(latest_values),
            "peak_concurrent": max(values) if values else 0,
            "average_concurrent": round(sum(values) / len(values), 2) if values else 0,
            "metric_note": "sum of observed concurrent viewers across channels; not unique people",
        }

    timeline_rows = [
        {"observed_at": timestamp.isoformat(), **values, "total_concurrent": sum(values.values())}
        for timestamp, values in sorted(timeline.items())
    ]
    overall_values = [row["total_concurrent"] for row in timeline_rows]
    return {
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
        "language_filter": language,
        "sample_resolution": "1 second timestamp buckets from observed data",
        "interpolation": False,
        "timeline": timeline_rows,
        "languages": summaries,
        "overall": {
            "peak_concurrent": max(overall_values) if overall_values else 0,
            "current_concurrent": overall_values[-1] if overall_values else 0,
            "observed_seconds": len(timeline_rows),
            "channel_count": len(channel_latest),
        },
        "channels": [
            {
                "channel_id": channel.id,
                "name": channel.name,
                "language": channel.language,
                "language_group": language_group(channel.language),
                "current_concurrent": int(observation.concurrent_viewers or 0),
                "peak_concurrent": channel_peaks.get(channel.id, 0),
                "observed_at": _utc(observation.observed_at).isoformat(),
            }
            for observation, channel in channel_latest.values()
        ],
    }


def language_group(language: str | None) -> str:
    """Map YouTube language metadata into the StatAxis market buckets."""
    value = (language or "").strip().lower()
    if not value or value == "unknown":
        return "Unknown"
    if value.startswith("hi") or value in {"hindi", "hin"}:
        return "Hindi"
    if value.startswith("en") or value in {"english", "eng"}:
        return "English"
    return "Regional"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
