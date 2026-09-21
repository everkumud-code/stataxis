"""Time-aligned live audience statistics: average and peak concurrent viewers by feed.

Why this exists
---------------
A channel can have several live streams at once (a long-running Primary feed plus
event-based Secondary feeds). The publishable numbers are

  * a snapshot at a chosen minute ("live viewers at 9 PM"), and
  * the Average and Peak concurrent viewers over a window ("10:00 to 13:00"),

for the Primary feed, the Secondary feeds and the All feed (Primary + Secondary).

Method (stated in every response)
---------------------------------
Streams are sampled at different instants, so they cannot be summed sample by sample.
The window is cut into a regular grid (default one minute). At every grid time each
stream contributes its most recent sample no older than ``FRESHNESS_SECONDS``
(last observation carried forward; nothing is interpolated between samples). The
per-stream values at that instant are then split into Primary / Secondary / All. Peak is
the highest All value on the grid, so it is the peak of the *combined* audience, not the
largest single-stream sample. Average is the mean over the grid times at which the channel
was live; a channel is never zero-filled while it had no live stream at all.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.live_monitor import LIVE_STREAM_FRESHNESS_SECONDS, language_group
from collector.storage import Channel, Observation, Video, effective_channel_language
from metrics.feeds import LiveStream, min_primary_hours, split_feeds
from metrics.markets import market_label, normalize_segment

FRESHNESS_SECONDS = LIVE_STREAM_FRESHNESS_SECONDS
MIN_BUCKET_SECONDS = 30
MAX_WINDOW = timedelta(hours=24)
MAX_BUCKETS = 3000

METHOD = (
    "Regular time grid; each live stream contributes its latest sample no older than "
    f"{FRESHNESS_SECONDS}s (last observation carried forward, no interpolation). "
    "Primary = stream live for the primary threshold or longer; Secondary = every other concurrent stream; "
    "All = Primary + Secondary. Peak is the peak of the combined audience. "
    "Average is over the times the channel was live."
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass
class _Stream:
    video_id: str
    started_at: datetime | None
    samples: list[tuple[datetime, int]]


def _load_streams(
    session: Session, *, start_at: datetime, end_at: datetime, language: str | None, segment: str | None,
) -> tuple[dict[int, dict[str, _Stream]], dict[int, Channel], dict[int, str]]:
    segment_key = normalize_segment(segment) if segment else None
    stmt = (
        select(Observation, Channel, Video)
        .join(Channel, Channel.id == Observation.channel_id)
        .join(Video, Video.id == Observation.video_id)
        .where(
            Observation.observed_at >= start_at - timedelta(seconds=FRESHNESS_SECONDS),
            Observation.observed_at <= end_at,
            Observation.is_live.is_(True),
            Observation.concurrent_viewers.is_not(None),
            Channel.active.is_(True),
        )
        .order_by(Observation.observed_at.asc(), Observation.id.asc())
    )
    rows = list(session.execute(stmt).all())
    languages = {channel.id: effective_channel_language(session, channel) for _, channel, _ in rows}
    target = language.strip().lower() if language else None
    streams: dict[int, dict[str, _Stream]] = defaultdict(dict)
    channels: dict[int, Channel] = {}
    for observation, channel, video in rows:
        if target and language_group(languages[channel.id]).lower() != target and languages[channel.id].lower() != target:
            continue
        if segment_key and (channel.segment or "news") != segment_key:
            continue
        channels[channel.id] = channel
        stream = streams[channel.id].setdefault(
            video.youtube_video_id,
            _Stream(video.youtube_video_id, video.live_started_at and _utc(video.live_started_at), []),
        )
        stream.samples.append((_utc(observation.observed_at), int(observation.concurrent_viewers or 0)))
    return streams, channels, languages


def _grid(start_at: datetime, end_at: datetime, bucket_seconds: int) -> list[datetime]:
    count = int((end_at - start_at).total_seconds() // bucket_seconds) + 1
    return [start_at + timedelta(seconds=bucket_seconds * index) for index in range(count)]


def _channel_series(
    streams: dict[str, _Stream], grid: list[datetime], threshold_hours: float,
) -> list[tuple[datetime, Any, dict[str, int]] | None]:
    """For each grid time: (time, FeedSplit, per-stream viewers) or None when no stream was live."""
    pointers = {video_id: 0 for video_id in streams}
    series: list[tuple[datetime, Any, dict[str, int]] | None] = []
    for moment in grid:
        live: list[LiveStream] = []
        values: dict[str, int] = {}
        for video_id, stream in streams.items():
            samples = stream.samples
            index = pointers[video_id]
            while index + 1 < len(samples) and samples[index + 1][0] <= moment:
                index += 1
            pointers[video_id] = index
            sampled_at, viewers = samples[index]
            if sampled_at <= moment and (moment - sampled_at).total_seconds() <= FRESHNESS_SECONDS:
                live.append(LiveStream(video_id, viewers, stream.started_at))
                values[video_id] = viewers
        series.append((moment, split_feeds(live, now=moment, min_hours=threshold_hours), values) if live else None)
    return series


def _feed_stats(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"average": None, "peak": None}
    return {"average": round(sum(values) / len(values), 1), "peak": max(values)}


def live_window_stats(
    session: Session,
    *,
    start_at: datetime,
    end_at: datetime,
    language: str | None = None,
    segment: str | None = None,
    bucket_seconds: int = 60,
) -> dict[str, Any]:
    """Average and peak concurrent viewers for Primary / Secondary / All feeds over a window."""
    start_at, end_at = _utc(start_at), _utc(end_at)
    if end_at <= start_at:
        raise ValueError("end_at must be after start_at")
    if end_at - start_at > MAX_WINDOW:
        raise ValueError("live stats window cannot exceed 24 hours")
    bucket_seconds = int(bucket_seconds)
    if bucket_seconds < MIN_BUCKET_SECONDS:
        raise ValueError(f"bucket_seconds must be at least {MIN_BUCKET_SECONDS}")
    grid = _grid(start_at, end_at, bucket_seconds)
    if len(grid) > MAX_BUCKETS:
        raise ValueError("window is too long for this bucket size")

    threshold = min_primary_hours()
    streams, channels, languages = _load_streams(session, start_at=start_at, end_at=end_at, language=language, segment=segment)

    rows: list[dict[str, Any]] = []
    combined: dict[datetime, dict[str, int]] = defaultdict(lambda: {"primary": 0, "secondary": 0, "all": 0})
    market_time: dict[str, dict[datetime, int]] = defaultdict(lambda: defaultdict(int))
    for channel_id, channel_streams in streams.items():
        series = [entry for entry in _channel_series(channel_streams, grid, threshold) if entry is not None]
        if not series:
            continue
        channel = channels[channel_id]
        all_values = [split.all for _, split, _ in series]
        peak_index = max(range(len(series)), key=lambda index: all_values[index])
        label = market_label(channel.segment, languages[channel_id])
        for moment, split, _ in series:
            for key, value in (("primary", split.primary), ("secondary", split.secondary), ("all", split.all)):
                combined[moment][key] += value
            market_time[label][moment] += split.all
        seen = {video_id for _, _, values in series for video_id in values}
        rows.append({
            "channel_id": channel.id,
            "name": channel.name,
            "language": languages[channel_id],
            "language_group": language_group(languages[channel_id]),
            "segment": channel.segment or "news",
            "market_label": label,
            "feeds": {
                "primary": _feed_stats([split.primary for _, split, _ in series]),
                "secondary": _feed_stats([split.secondary for _, split, _ in series]),
                "all": _feed_stats(all_values),
            },
            "peak_at": series[peak_index][0].isoformat(),
            "streams_seen": len(seen),
            "observed_minutes": round(len(series) * bucket_seconds / 60, 1),
            "coverage_percent": round(len(series) / len(grid) * 100, 1),
        })

    markets: list[dict[str, Any]] = []
    by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_market[row["market_label"]].append(row)
    for label, items in by_market.items():
        total = sum(item["feeds"]["all"]["average"] for item in items)
        for item in items:
            item["share_percent"] = round(item["feeds"]["all"]["average"] / total * 100, 1) if total > 0 else None
        items.sort(key=lambda item: item["feeds"]["all"]["average"], reverse=True)
        totals = market_time[label]
        markets.append({
            "label": label,
            "channel_count": len(items),
            "average": round(sum(totals.values()) / len(totals), 1),
            "peak": max(totals.values()),
            "headline": _headline(label, start_at, end_at, items),
        })
    markets.sort(key=lambda item: item["average"], reverse=True)
    rows.sort(key=lambda item: item["feeds"]["all"]["average"], reverse=True)
    for rank, item in enumerate(rows, start=1):
        item["rank"] = rank

    overall_values = {moment: values for moment, values in combined.items()}
    return {
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
        "bucket_seconds": bucket_seconds,
        "bucket_count": len(grid),
        "freshness_seconds": FRESHNESS_SECONDS,
        "primary_min_live_hours": threshold,
        "interpolation": False,
        "method": METHOD,
        "filters": {"language": language, "segment": segment},
        "overall": {
            "channel_count": len(rows),
            "primary": _feed_stats([values["primary"] for values in overall_values.values()]),
            "secondary": _feed_stats([values["secondary"] for values in overall_values.values()]),
            "all": _feed_stats([values["all"] for values in overall_values.values()]),
        },
        "markets": markets,
        "channels": rows,
    }


def live_snapshot(
    session: Session,
    *,
    at: datetime,
    language: str | None = None,
    segment: str | None = None,
) -> dict[str, Any]:
    """Live viewers at one instant (e.g. 21:00): Primary / Secondary / All per channel and market."""
    moment = _utc(at)
    threshold = min_primary_hours()
    streams, channels, languages = _load_streams(session, start_at=moment, end_at=moment, language=language, segment=segment)
    rows: list[dict[str, Any]] = []
    market_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"primary": 0, "secondary": 0, "all": 0, "channels": 0})
    for channel_id, channel_streams in streams.items():
        entry = _channel_series(channel_streams, [moment], threshold)[0]
        if entry is None:
            continue
        _, split, _ = entry
        channel = channels[channel_id]
        label = market_label(channel.segment, languages[channel_id])
        rows.append({
            "channel_id": channel.id,
            "name": channel.name,
            "language": languages[channel_id],
            "segment": channel.segment or "news",
            "market_label": label,
            "feeds": {"primary": split.primary, "secondary": split.secondary, "all": split.all},
            "secondary_count": split.secondary_count,
        })
        for key in ("primary", "secondary", "all"):
            market_totals[label][key] += getattr(split, key)
        market_totals[label]["channels"] += 1
    rows.sort(key=lambda item: item["feeds"]["all"], reverse=True)
    for rank, item in enumerate(rows, start=1):
        item["rank"] = rank
    return {
        "at": moment.isoformat(),
        "freshness_seconds": FRESHNESS_SECONDS,
        "primary_min_live_hours": threshold,
        "interpolation": False,
        "method": METHOD,
        "filters": {"language": language, "segment": segment},
        "markets": [{"label": label, **totals} for label, totals in sorted(market_totals.items(), key=lambda pair: pair[1]["all"], reverse=True)],
        "channels": rows,
    }


def _headline(label: str, start_at: datetime, end_at: datetime, items: list[dict[str, Any]]) -> str | None:
    ranked = [item for item in items if item.get("share_percent") is not None]
    if not ranked:
        return None
    text = (
        f"{label} average concurrent viewers ({start_at:%d %b %H:%M} to {end_at:%H:%M} UTC): "
        f"{ranked[0]['name']} led with {ranked[0]['share_percent']:g}% share"
    )
    followers = [item["name"] for item in ranked[1:3]]
    if followers:
        text += " followed by " + " & ".join(followers)
    return text
