"""Explainable market, channel, stream-scope and content intelligence.

All metrics in this module are derived from persisted observations. Missing values
remain missing; no synthetic market data is generated.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from collector.storage import Channel, Observation, Video, effective_channel_language
from metrics.market_stx import build_market_stx

PERIOD_DAYS = {
    "1h": 1 / 24,
    "3h": 3 / 24,
    "6h": 6 / 24,
    "today": None,
    "7d": 7,
    "week": 7,
    "3w": 21,
    "month": 30,
    "quarter": 90,
    "year": 365,
}


def market_report(
    session: Session,
    *,
    as_of: datetime | None = None,
    period: str = "7d",
    language: str | None = None,
    region: str | None = None,
    market: str | None = None,
    stream_scope: str = "all",
    limit: int = 50,
) -> dict[str, Any]:
    """Return channel rows plus market rollups for one measured observation window."""
    as_of = _utc(as_of or datetime.now(UTC))
    start_at = _period_start(as_of, period)
    previous_end = start_at
    previous_start = _period_start(previous_end, period)
    channels = _eligible_channels(session, language=language, region=region, market=market)
    channel_ids = [channel.id for channel in channels]

    current_rows = _observation_rows(session, channel_ids, start_at, as_of)
    previous_query_end = previous_end - timedelta(microseconds=1)
    previous_rows = _observation_rows(session, channel_ids, previous_start, previous_query_end)
    current = _aggregate_by_channel(session, channels, current_rows, stream_scope)
    previous = _aggregate_by_channel(session, channels, previous_rows, stream_scope)
    shorts_scope = _is_shorts_scope(stream_scope)
    stx = {} if shorts_scope else build_market_stx(
        [row for row in current_rows if _scope_matches(row, stream_scope)],
        [row for row in previous_rows if _scope_matches(row, stream_scope)],
        channel_ids=channel_ids,
    )

    ranked = sorted(
        current.values(),
        key=lambda item: (
            item["view_delta"] is not None,
            item["view_delta"] if item["view_delta"] is not None else float("-inf"),
            item["average_concurrent"] if item["average_concurrent"] is not None else float("-inf"),
        ),
        reverse=True,
    )
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
        old = previous.get(item["channel_id"])
        item["previous_rank"] = _previous_rank(item["channel_id"], previous, old)
        item["rank_change"] = item["previous_rank"] - rank if item["previous_rank"] is not None else None
        item["stx"] = stx.get(item["channel_id"], _no_stx(shorts_scope))

    rows = ranked[: max(1, min(int(limit), 200))]
    view_total = _sum_metric(ranked, "view_delta")
    concurrent_total = _sum_metric(ranked, "average_concurrent")
    peak_total = max((item["peak_concurrent"] for item in ranked if item["peak_concurrent"] is not None), default=None)
    return {
        "as_of": as_of.isoformat(),
        "period": period,
        "start_at": start_at.isoformat(),
        "end_at": as_of.isoformat(),
        "previous_start_at": previous_start.isoformat(),
        "previous_end_at": previous_end.isoformat(),
        "filters": {"language": language, "region": region, "market": market, "stream_scope": stream_scope},
        "counted_in_analysis": not shorts_scope,
        "note": SHORTS_NOTE if shorts_scope else None,
        "market": {
            "channel_count": len(ranked),
            "view_delta_total": view_total,
            "average_concurrent_total": concurrent_total,
            "peak_concurrent": peak_total,
            "share_basis": "view_delta" if view_total is not None else "average_concurrent",
        },
        "channels": rows,
        "provenance": {
            "source": "persisted_stataxis_observations",
            "observation_count": len(current_rows),
            "previous_observation_count": len(previous_rows),
            "missing_values_are_not_zero_filled": True,
            "stx_source": "persisted_stataxis_observations",
        },
    }


def channel_media_intelligence(
    session: Session,
    channel_id: int,
    *,
    as_of: datetime | None = None,
    period: str = "7d",
    stream_scope: str = "all",
    top_videos: int = 10,
) -> dict[str, Any] | None:
    """Return a channel's audience, momentum and content-performance dimensions."""
    channel = session.get(Channel, channel_id)
    if channel is None:
        return None
    as_of = _utc(as_of or datetime.now(UTC))
    start_at = _period_start(as_of, period)
    rows = _observation_rows(session, [channel_id], start_at, as_of)
    aggregate = _aggregate_channel(channel, [row for row in rows if _scope_matches(row, stream_scope)], stream_scope)
    videos = _video_performance([row for row in rows if _scope_matches(row, stream_scope)], top_videos)
    shorts_scope = _is_shorts_scope(stream_scope)
    stx = _no_stx(True) if shorts_scope else build_market_stx(
        [row for row in rows if _scope_matches(row, stream_scope)],
        [],
        channel_ids=[channel_id],
    )[channel_id]
    return {
        "channel": {
            "id": channel.id,
            "youtube_channel_id": channel.youtube_channel_id,
            "name": channel.name,
            "network": channel.network,
            "language": effective_channel_language(session, channel),
            "region": channel.region,
            "market": _market_name(channel),
        },
        "window": {"period": period, "start_at": start_at.isoformat(), "end_at": as_of.isoformat()},
        "audience": {
            "current_concurrent": aggregate["current_concurrent"],
            "average_concurrent": aggregate["average_concurrent"],
            "peak_concurrent": aggregate["peak_concurrent"],
            "live_observation_count": aggregate["live_observation_count"],
        },
        "momentum": {
            "view_delta": aggregate["view_delta"],
            "view_velocity_per_minute": aggregate["view_velocity_per_minute"],
            "like_delta": aggregate["like_delta"],
            "comment_delta": aggregate["comment_delta"],
            "engagement_velocity_per_minute": aggregate["engagement_velocity_per_minute"],
        },
        "stx": stx,
        "content": {
            "videos_observed": aggregate["videos_observed"],
            "uploads_in_window": aggregate["uploads_in_window"],
            "upload_cadence_per_week": aggregate["upload_cadence_per_week"],
            "top_videos": videos,
        },
        "stream_scope": stream_scope,
        "counted_in_analysis": not shorts_scope,
        "note": SHORTS_NOTE if shorts_scope else None,
        "provenance": {
            "observation_count": len(rows),
            "source_values": sorted({row["source"] for row in rows if row["source"]}),
            "collector_versions": sorted({row["collector_version"] for row in rows if row["collector_version"]}),
            "first_observed_at": _iso(min((row["observed_at"] for row in rows), default=None)),
            "last_observed_at": _iso(max((row["observed_at"] for row in rows), default=None)),
            "missing_values_are_not_zero_filled": True,
        },
    }


def _eligible_channels(session: Session, *, language: str | None, region: str | None, market: str | None) -> list[Channel]:
    channels = list(session.execute(select(Channel).where(Channel.active.is_(True)).order_by(Channel.name.asc())).scalars())
    result = []
    for channel in channels:
        channel_language = effective_channel_language(session, channel)
        if language and channel_language.lower() != language.lower(): continue
        if region and (channel.region or "unknown").lower() != region.lower(): continue
        if market and _market_name(channel).lower() != market.lower(): continue
        result.append(channel)
    return result


def _observation_rows(session: Session, channel_ids: list[int], start_at: datetime, end_at: datetime) -> list[dict[str, Any]]:
    if not channel_ids: return []
    stmt = (
        select(Observation, Video, Channel)
        .join(Video, Video.id == Observation.video_id)
        .join(Channel, Channel.id == Observation.channel_id)
        .where(Observation.channel_id.in_(channel_ids), Observation.observed_at >= start_at, Observation.observed_at <= end_at)
        .order_by(Observation.channel_id.asc(), Observation.video_id.asc(), Observation.observed_at.asc(), Observation.id.asc())
    )
    rows = []
    for observation, video, channel in session.execute(stmt):
        rows.append({
            "observation_id": observation.id,
            "channel_id": channel.id,
            "channel_name": channel.name,
            "video_id": video.id,
            "youtube_video_id": video.youtube_video_id,
            "title": video.title,
            "published_at": video.published_at,
            "observed_at": _utc(observation.observed_at),
            "view_count": observation.view_count,
            "like_count": observation.like_count,
            "comment_count": observation.comment_count,
            "concurrent_viewers": observation.concurrent_viewers,
            "is_live": observation.is_live,
            "classification": observation.classification,
            "source": observation.source,
            "collector_version": observation.collector_version,
        })
    return rows


def _aggregate_by_channel(session: Session, channels: list[Channel], rows: list[dict[str, Any]], stream_scope: str) -> dict[int, dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if _scope_matches(row, stream_scope): grouped[row["channel_id"]].append(row)
    return {channel.id: _aggregate_channel(channel, grouped.get(channel.id, []), stream_scope) for channel in channels}


def _aggregate_channel(channel: Channel, rows: list[dict[str, Any]], stream_scope: str) -> dict[str, Any]:
    by_video: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows: by_video[row["video_id"]].append(row)
    view_delta = like_delta = comment_delta = 0
    view_seen = like_seen = comment_seen = False
    velocity_seconds = 0.0
    for video_rows in by_video.values():
        video_rows.sort(key=lambda row: row["observed_at"])
        first, last = video_rows[0], video_rows[-1]
        if first["view_count"] is not None and last["view_count"] is not None:
            view_delta += max(0, int(last["view_count"]) - int(first["view_count"]))
            view_seen = True
            velocity_seconds += max((last["observed_at"] - first["observed_at"]).total_seconds(), 0)
        if first["like_count"] is not None and last["like_count"] is not None:
            like_delta += max(0, int(last["like_count"]) - int(first["like_count"]))
            like_seen = True
        if first["comment_count"] is not None and last["comment_count"] is not None:
            comment_delta += max(0, int(last["comment_count"]) - int(first["comment_count"]))
            comment_seen = True
    concurrent = [row["concurrent_viewers"] for row in rows if row["concurrent_viewers"] is not None]
    live_rows = [row for row in rows if row["is_live"] or row["classification"] == "LIVE"]
    uploads = {row["video_id"] for row in rows if row["published_at"] and _published_in_window(row["published_at"], rows)}
    elapsed_days = _window_days(rows)
    return {
        "channel_id": channel.id,
        "channel": channel.name,
        "market": _market_name(channel),
        "view_delta": view_delta if view_seen else None,
        "average_concurrent": round(sum(concurrent) / len(concurrent), 2) if concurrent else None,
        "peak_concurrent": max(concurrent) if concurrent else None,
        "current_concurrent": concurrent[-1] if concurrent else None,
        "view_velocity_per_minute": round(view_delta / max(velocity_seconds / 60, 1), 2) if view_seen and velocity_seconds > 0 else None,
        "like_delta": like_delta if like_seen else None,
        "comment_delta": comment_delta if comment_seen else None,
        "engagement_velocity_per_minute": round((like_delta + comment_delta) / max(velocity_seconds / 60, 1), 2) if (like_seen or comment_seen) and velocity_seconds > 0 else None,
        "videos_observed": len(by_video),
        "uploads_in_window": len(uploads),
        "upload_cadence_per_week": round(len(uploads) / max(elapsed_days, 1) * 7, 2),
        "live_observation_count": len(live_rows),
        "observation_count": len(rows),
        "stream_scope": stream_scope,
    }


def _video_performance(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows: grouped[row["video_id"]].append(row)
    result = []
    for video_rows in grouped.values():
        video_rows.sort(key=lambda row: row["observed_at"])
        first, last = video_rows[0], video_rows[-1]
        view_delta = None
        if first["view_count"] is not None and last["view_count"] is not None: view_delta = max(0, int(last["view_count"]) - int(first["view_count"]))
        duration = max((last["observed_at"] - first["observed_at"]).total_seconds(), 0)
        result.append({
            "video_id": last["video_id"], "youtube_video_id": last["youtube_video_id"], "title": last["title"],
            "classification": last["classification"], "view_delta": view_delta,
            "view_velocity_per_minute": round(view_delta / max(duration / 60, 1), 2) if view_delta is not None and duration > 0 else None,
            "first_observed_at": first["observed_at"].isoformat(), "last_observed_at": last["observed_at"].isoformat(),
            "observation_count": len(video_rows),
        })
    result.sort(key=lambda item: (item["view_delta"] is not None, item["view_delta"] or -1), reverse=True)
    return result[: max(1, min(int(limit), 50))]


SHORTS_NOTE = "Shorts are shown for reference only. They are not counted in STX, rankings or analysis."


def _is_shorts_scope(stream_scope: str | None) -> bool:
    return (stream_scope or "all").lower() == "shorts"


def _no_stx(excluded: bool) -> dict[str, Any]:
    stx: dict[str, Any] = {"score": None, "confidence": 0.0, "available_signals": 0, "components": {}, "signals": {}}
    if excluded:
        stx["excluded_reason"] = SHORTS_NOTE
    return stx


def _scope_matches(row: dict[str, Any], stream_scope: str) -> bool:
    scope = (stream_scope or "all").lower()
    # Shorts are shown only in the "shorts" scope; every other scope (including "all") excludes them.
    if scope == "all": return row["classification"] != "SHORT"
    if scope == "live": return bool(row["is_live"] or row["classification"] == "LIVE")
    if scope == "replay": return row["classification"] == "COMPLETED_LIVE"
    if scope == "video": return row["classification"] in {"REGULAR_VIDEO", "PREMIERE", "UNKNOWN"}
    if scope == "shorts": return row["classification"] == "SHORT"
    raise ValueError("stream_scope must be one of: all, live, replay, video, shorts")


def _period_start(as_of: datetime, period: str) -> datetime:
    period = period.lower()
    if period not in PERIOD_DAYS: raise ValueError("period must be one of: 1h, 3h, 6h, today, 7d, week, 3w, month, quarter, year")
    if period == "today": return as_of.replace(hour=0, minute=0, second=0, microsecond=0)
    return as_of - timedelta(days=float(PERIOD_DAYS[period]))


def _previous_rank(channel_id: int, previous: dict[int, dict[str, Any]], old: dict[str, Any] | None) -> int | None:
    ranked = [item for item in previous.values() if item.get("view_delta") is not None]
    ranked.sort(key=lambda item: item["view_delta"], reverse=True)
    for rank, item in enumerate(ranked, start=1):
        if item["channel_id"] == channel_id: return rank
    return None


def _sum_metric(items: Iterable[dict[str, Any]], key: str) -> float | int | None:
    values = [item[key] for item in items if item.get(key) is not None]
    return sum(values) if values else None


def _market_name(channel: Channel) -> str:
    language = (channel.language or "unknown").strip() or "unknown"
    region = (channel.region or "unknown").strip() or "unknown"
    return f"{language} / {region}"


def _published_in_window(value: str, rows: list[dict[str, Any]]) -> bool:
    try: published = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError): return False
    published = _utc(published)
    if not rows: return False
    return min(row["observed_at"] for row in rows) <= published <= max(row["observed_at"] for row in rows)


def _window_days(rows: list[dict[str, Any]]) -> float:
    if len(rows) < 2: return 1.0
    return max((max(row["observed_at"] for row in rows) - min(row["observed_at"] for row in rows)).total_seconds() / 86400, 1 / 24)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None: return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
