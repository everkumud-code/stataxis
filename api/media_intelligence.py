"""Explainable market, channel, stream-scope and content intelligence.

All metrics in this module are derived from persisted observations. Missing values
remain missing; no synthetic market data is generated.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased

from collector.storage import Channel, Observation, Video, effective_channel_language
from metrics.market_stx import build_market_stx
from metrics.markets import language_matches, market_label, normalize_segment

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
    segment: str | None = None,
    stream_scope: str = "all",
    limit: int = 50,
) -> dict[str, Any]:
    """Return channel rows plus market rollups for one measured observation window."""
    as_of = _utc(as_of or datetime.now(UTC))
    start_at = _period_start(as_of, period)
    previous_end = start_at
    previous_start = _period_start(previous_end, period)
    if period.lower() == "today":   # today so far, against yesterday over the same stretch of the day (the day before it, whole, would make today look small)
        previous_start, previous_end = start_at - timedelta(days=1), as_of - timedelta(days=1)
    channels = _eligible_channels(session, language=language, region=region, market=market, segment=segment)
    channel_ids = [channel.id for channel in channels]

    previous_query_end = previous_end - timedelta(microseconds=1)
    current, current_videos = _aggregate_in_database(session, channels, start_at, as_of, stream_scope)
    previous, previous_videos = _aggregate_in_database(session, channels, previous_start, previous_query_end, stream_scope)
    shorts_scope = _is_shorts_scope(stream_scope)
    stx = {} if shorts_scope else build_market_stx(
        _series_sample(session, channels, start_at, as_of, stream_scope, current_videos),
        _series_sample(session, channels, previous_start, previous_query_end, stream_scope, previous_videos),
        channel_ids=channel_ids,
    )
    for cid, item in stx.items():   # the sample feeds the signals; the counts shown are the real ones
        if item.get("provenance"):
            item["provenance"]["observation_count"] = current.get(cid, {}).get("observation_count", 0)
            item["provenance"]["previous_observation_count"] = previous.get(cid, {}).get("observation_count", 0)

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

    market_summaries = _market_summaries(ranked, period)
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
        "filters": {"language": language, "region": region, "market": market, "segment": segment, "stream_scope": stream_scope},
        "counted_in_analysis": not shorts_scope,
        "note": SHORTS_NOTE if shorts_scope else None,
        "markets": market_summaries,
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
            "observation_count": _count_rows(session, channel_ids, start_at, as_of),
            "previous_observation_count": _count_rows(session, channel_ids, previous_start, previous_query_end),
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
    aggregates, lines = _aggregate_in_database(session, [channel], start_at, as_of, stream_scope)   # counted by the database: a big channel has tens of thousands of readings in a week
    aggregate = aggregates[channel.id]
    videos = _video_performance_from_lines(lines, top_videos)
    shorts_scope = _is_shorts_scope(stream_scope)
    stx = _no_stx(True) if shorts_scope else build_market_stx(_series_sample(session, [channel], start_at, as_of, stream_scope, lines, full=True), [], channel_ids=[channel_id])[channel_id]
    window = and_(Observation.channel_id == channel_id, Observation.observed_at >= start_at, Observation.observed_at <= as_of)
    total_rows, first_at, last_at = session.execute(select(func.count(), func.min(Observation.observed_at), func.max(Observation.observed_at)).where(window)).one()
    sources = sorted(x for (x,) in session.execute(select(Observation.source).where(window).distinct()) if x)
    versions = sorted(x for (x,) in session.execute(select(Observation.collector_version).where(window).distinct()) if x)
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
            "observation_count": int(total_rows or 0),
            "source_values": sources,
            "collector_versions": versions,
            "first_observed_at": _iso(_utc(first_at) if first_at else None),
            "last_observed_at": _iso(_utc(last_at) if last_at else None),
            "missing_values_are_not_zero_filled": True,
        },
    }


def _eligible_channels(session: Session, *, language: str | None, region: str | None, market: str | None, segment: str | None = None) -> list[Channel]:
    segment_key = normalize_segment(segment) if segment else None
    channels = list(session.execute(select(Channel).where(Channel.active.is_(True)).order_by(Channel.name.asc())).scalars())
    result = []
    for channel in channels:
        channel_language = effective_channel_language(session, channel)
        if language and not language_matches(channel_language, language): continue
        if region and (channel.region or "unknown").lower() != region.lower(): continue
        if market and market.lower() not in {_market_name(channel).lower(), _channel_market_label(channel).lower()}: continue
        if segment_key and (channel.segment or "news") != segment_key: continue
        result.append(channel)
    return result


def _scope_condition(stream_scope: str):
    """The same rule as _scope_matches, as something the database can apply."""
    scope = (stream_scope or "all").lower()
    if scope == "all": return Observation.classification != "SHORT"
    if scope == "live": return or_(Observation.is_live.is_(True), Observation.classification == "LIVE")
    if scope == "replay": return Observation.classification == "COMPLETED_LIVE"
    if scope == "video": return Observation.classification.in_(["REGULAR_VIDEO", "PREMIERE", "UNKNOWN"])
    if scope == "shorts": return Observation.classification == "SHORT"
    raise ValueError("stream_scope must be one of: all, live, replay, video, shorts")


def _count_rows(session: Session, channel_ids: list[int], start_at: datetime, end_at: datetime) -> int:
    if not channel_ids: return 0
    return int(session.execute(select(func.count()).select_from(Observation).where(Observation.channel_id.in_(channel_ids), Observation.observed_at >= start_at, Observation.observed_at <= end_at)).scalar_one() or 0)


def _aggregate_in_database(session: Session, channels: list[Channel], start_at: datetime, end_at: datetime, stream_scope: str) -> tuple[dict[int, dict[str, Any]], list[Any]]:
    """The same per-channel numbers as _aggregate_by_channel, counted by the database instead of in Python.
    For each video in the window the database finds its first and last reading and sums its concurrent viewers; only those few thousand lines (not the half a million readings) come back."""
    ids = [channel.id for channel in channels]
    if not ids:
        return {}, []
    where = and_(Observation.channel_id.in_(ids), Observation.observed_at >= start_at, Observation.observed_at <= end_at, _scope_condition(stream_scope))
    live_flag = case((or_(Observation.is_live.is_(True), Observation.classification == "LIVE"), 1), else_=0)
    agg = (select(Observation.channel_id.label("channel_id"), Observation.video_id.label("video_id"), func.count().label("n"), func.min(Observation.observed_at).label("t0"), func.max(Observation.observed_at).label("t1"),
                  func.count(Observation.concurrent_viewers).label("conc_n"), func.sum(Observation.concurrent_viewers).label("conc_sum"), func.max(Observation.concurrent_viewers).label("conc_max"),
                  func.sum(live_flag).label("live_n"), func.max(case((Observation.concurrent_viewers.is_not(None), Observation.observed_at))).label("tc"))
           .where(where).group_by(Observation.channel_id, Observation.video_id).subquery())
    first, last, latest_conc = aliased(Observation), aliased(Observation), aliased(Observation)
    stmt = (select(agg.c.channel_id, agg.c.video_id, agg.c.n, agg.c.t0, agg.c.t1, agg.c.conc_n, agg.c.conc_sum, agg.c.conc_max, agg.c.live_n,
                   first.id.label("id0"), first.view_count.label("v0"), first.like_count.label("l0"), first.comment_count.label("c0"),
                   last.id.label("id1"), last.view_count.label("v1"), last.like_count.label("l1"), last.comment_count.label("c1"),
                   latest_conc.concurrent_viewers.label("conc_last"), last.classification.label("cls1"), Video.published_at.label("published_at"), Video.youtube_video_id.label("youtube_video_id"), Video.title.label("title"))
            .join(first, and_(first.video_id == agg.c.video_id, first.observed_at == agg.c.t0))
            .join(last, and_(last.video_id == agg.c.video_id, last.observed_at == agg.c.t1))
            .outerjoin(latest_conc, and_(latest_conc.video_id == agg.c.video_id, latest_conc.observed_at == agg.c.tc))
            .join(Video, Video.id == agg.c.video_id))
    by_channel: dict[int, list[Any]] = defaultdict(list)
    lines = list(session.execute(stmt))
    for line in lines:
        by_channel[line.channel_id].append(line)
    return {channel.id: _aggregate_channel_from_lines(channel, by_channel.get(channel.id, []), stream_scope) for channel in channels}, lines


def _aggregate_channel_from_lines(channel: Channel, lines: list[Any], stream_scope: str) -> dict[str, Any]:
    """_aggregate_channel, from per-video lines. Same definitions: a video's gain is its last reading minus its first, a channel's average is over all its readings,
    and 'now' is the latest reading of the channel's highest-numbered video that has one."""
    if not lines:
        return _aggregate_channel(channel, [], stream_scope)
    view_delta = like_delta = comment_delta = 0
    view_seen = like_seen = comment_seen = False
    velocity_seconds = 0.0
    for line in lines:
        t0, t1 = _utc(line.t0), _utc(line.t1)
        if line.v0 is not None and line.v1 is not None:
            view_delta += max(0, int(line.v1) - int(line.v0)); view_seen = True
            velocity_seconds += max((t1 - t0).total_seconds(), 0)
        if line.l0 is not None and line.l1 is not None:
            like_delta += max(0, int(line.l1) - int(line.l0)); like_seen = True
        if line.c0 is not None and line.c1 is not None:
            comment_delta += max(0, int(line.c1) - int(line.c0)); comment_seen = True
    conc_n = sum(int(line.conc_n or 0) for line in lines)
    conc_sum = sum(float(line.conc_sum or 0) for line in lines)
    peaks = [int(line.conc_max) for line in lines if line.conc_max is not None]
    with_conc = [line for line in lines if line.conc_n and line.conc_last is not None]
    current = int(max(with_conc, key=lambda line: line.video_id).conc_last) if with_conc else None
    first_at, last_at = min(_utc(line.t0) for line in lines), max(_utc(line.t1) for line in lines)
    total_rows = sum(int(line.n) for line in lines)
    uploads = 0
    for line in lines:
        if not line.published_at: continue
        try: published = _utc(datetime.fromisoformat(str(line.published_at).replace("Z", "+00:00")))
        except (TypeError, ValueError): continue
        if first_at <= published <= last_at: uploads += 1
    elapsed_days = 1.0 if total_rows < 2 else max((last_at - first_at).total_seconds() / 86400, 1 / 24)
    return {
        "channel_id": channel.id,
        "channel": channel.name,
        "market": _market_name(channel),
        "segment": channel.segment or "news",
        "market_label": _channel_market_label(channel),
        "view_delta": view_delta if view_seen else None,
        "average_concurrent": round(conc_sum / conc_n, 2) if conc_n else None,
        "peak_concurrent": max(peaks) if peaks else None,
        "current_concurrent": current,
        "view_velocity_per_minute": round(view_delta / max(velocity_seconds / 60, 1), 2) if view_seen and velocity_seconds > 0 else None,
        "like_delta": like_delta if like_seen else None,
        "comment_delta": comment_delta if comment_seen else None,
        "engagement_velocity_per_minute": round((like_delta + comment_delta) / max(velocity_seconds / 60, 1), 2) if (like_seen or comment_seen) and velocity_seconds > 0 else None,
        "videos_observed": len(lines),
        "uploads_in_window": uploads,
        "upload_cadence_per_week": round(uploads / max(elapsed_days, 1) * 7, 2),
        "live_observation_count": sum(int(line.live_n or 0) for line in lines),
        "observation_count": total_rows,
        "stream_scope": stream_scope,
    }


SERIES_POINTS_PER_CHANNEL = 250     # the STX signals read each channel's series; this many evenly spread readings are plenty
SERIES_TAIL = timedelta(minutes=20)  # ...plus every reading of the last twenty minutes, so 'right now' (velocity, acceleration) is exact


def _series_sample(session: Session, channels: list[Channel], start_at: datetime, end_at: datetime, stream_scope: str, lines: list[Any], *, full: bool = False) -> list[dict[str, Any]]:
    """A thin, evenly spread sample of each channel's readings (plus the latest twenty minutes and each video's first and last reading), in the shape build_market_stx reads."""
    ids = [channel.id for channel in channels]
    if not ids or not lines:
        return []
    names = {channel.id: channel.name for channel in channels}
    total = sum(int(line.n) for line in lines)
    step = 1 if full else max(1, -(-total // (len(ids) * SERIES_POINTS_PER_CHANNEL)))   # one channel's own screen reads every reading (a big channel has about 30,000 a week: fast, and the same numbers as always)
    where = and_(Observation.channel_id.in_(ids), Observation.observed_at >= start_at, Observation.observed_at <= end_at, _scope_condition(stream_scope))
    cols = (Observation.id, Observation.channel_id, Observation.video_id, Observation.observed_at, Observation.view_count, Observation.like_count, Observation.comment_count, Observation.concurrent_viewers)
    seen: dict[int, Any] = {}
    sampled = or_(Observation.observed_at >= end_at - SERIES_TAIL, (Observation.id % step) == 0) if step > 1 else True
    for row in session.execute(select(*cols).where(where, sampled)):
        seen[row.id] = row
    edge_ids = [i for line in lines for i in (line.id0, line.id1) if i not in seen]
    for k in range(0, len(edge_ids), 800):
        for row in session.execute(select(*cols).where(Observation.id.in_(edge_ids[k:k + 800]))):
            seen[row.id] = row
    ordered = sorted(seen.values(), key=lambda row: (row.channel_id, row.video_id, row.observed_at, row.id))   # the order the readings have always been read in (it decides ties at the same instant)
    return [{"channel_id": row.channel_id, "channel_name": names.get(row.channel_id), "video_id": row.video_id, "observed_at": _utc(row.observed_at), "view_count": row.view_count,
             "like_count": row.like_count, "comment_count": row.comment_count, "concurrent_viewers": row.concurrent_viewers} for row in ordered]


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
        "segment": channel.segment or "news",
        "market_label": _channel_market_label(channel),
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


def _video_performance_from_lines(lines: list[Any], limit: int) -> list[dict[str, Any]]:
    """_video_performance, from the per-video lines the database counted."""
    result = []
    for line in lines:
        t0, t1 = _utc(line.t0), _utc(line.t1)
        view_delta = max(0, int(line.v1) - int(line.v0)) if line.v0 is not None and line.v1 is not None else None
        duration = max((t1 - t0).total_seconds(), 0)
        result.append({
            "video_id": line.video_id, "youtube_video_id": line.youtube_video_id, "title": line.title, "classification": line.cls1, "view_delta": view_delta,
            "view_velocity_per_minute": round(view_delta / max(duration / 60, 1), 2) if view_delta is not None and duration > 0 else None,
            "first_observed_at": t0.isoformat(), "last_observed_at": t1.isoformat(), "observation_count": int(line.n),
        })
    result.sort(key=lambda item: (item["view_delta"] is not None, item["view_delta"] or -1), reverse=True)
    return result[: max(1, min(int(limit), 50))]


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
    if period == "today":   # the day in India starts at midnight Indian time, which is 18:30 the evening before in UTC
        ist = as_of.astimezone(timezone(timedelta(hours=5, minutes=30)))
        return ist.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
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


def _channel_market_label(channel: Channel) -> str:
    return market_label(channel.segment, channel.language)


def _market_summaries(ranked: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    """Per-market share of the audience metric, leaderboard and a publishable headline.

    Sets share_percent / share_basis on every channel row: the channel's share of its own
    market, measured on view gain when the market has view data, otherwise on average
    concurrent viewers. Channels with no measurable value get no share (never zero-filled).
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in ranked:
        groups[item["market_label"]].append(item)
    summaries = []
    for label, items in groups.items():
        basis = "view_delta" if any(item["view_delta"] is not None for item in items) else "average_concurrent"
        values = {item["channel_id"]: item[basis] for item in items if item[basis] is not None}
        total = sum(values.values())
        for item in items:
            value = values.get(item["channel_id"])
            item["share_basis"] = basis
            item["share_percent"] = round(value / total * 100, 1) if value is not None and total > 0 else None
        ordered = sorted((item for item in items if item["share_percent"] is not None), key=lambda item: item["share_percent"], reverse=True)
        summaries.append({
            "label": label,
            "channel_count": len(items),
            "share_basis": basis,
            "total": total if values else None,
            "leaders": [{"channel_id": item["channel_id"], "channel": item["channel"], "share_percent": item["share_percent"]} for item in ordered[:5]],
            "headline": _headline(label, period, ordered),
        })
    summaries.sort(key=lambda summary: (summary["total"] is not None, summary["total"] or 0), reverse=True)
    return summaries


def _headline(label: str, period: str, ordered: list[dict[str, Any]]) -> str | None:
    if not ordered:
        return None
    text = f"{label} viewership ({period}): {ordered[0]['channel']} led with {ordered[0]['share_percent']:g}% share"
    followers = [item["channel"] for item in ordered[1:3]]
    if followers:
        text += " followed by " + " & ".join(followers)
    return text


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
