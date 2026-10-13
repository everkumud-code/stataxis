"""Report builder: pick the hours of the day, the dates, the feed (all / primary / secondary), the kind of content (live, videos, shorts, live replays) and the genre,
and get the measured ranking back, ready to turn into a PDF (api/report_pdf.py).

Live scope  -> average and peak concurrent viewers per channel in those hours (the feed decides which streams are counted).
Other scopes -> views the channel's videos gained inside those hours, counted from two measurements per video, one at each end of the window.
Nothing is estimated: a video that STAXIS did not measure close to both ends of a window is left out and counted in `coverage`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api import audience as audience_mod
from api.live_stats import live_window_stats
from api.market_common import MAX_RANGE_DAYS, ist_hours, mean, now_utc, parse_day, parse_published, pick_channels, rnd, today_ist, utc
from api.ttl_cache import ttl_cache
from api.media_intelligence import _scope_matches
from collector.storage import Observation, Video
from collector.topics import load_topic_keywords

FEEDS = ("all", "primary", "secondary")
SCOPES = {"live": "Live streams", "video": "Videos (VOD)", "shorts": "Shorts", "replay": "Live replays"}
GENRES = list(load_topic_keywords().keys()) + ["Other"]
MAX_VIEW_DAYS = 14
EDGE = timedelta(hours=2)
TARGET_NOTE = (
    "With a place, age group or gender chosen, each channel's figure is multiplied by the share of its audience inside that target, taken from the audience profile the channel or a named study supplied "
    "(age, place and gender combined as if independent). A channel with no profile is marked 'no audience data', never estimated."
)

LIVE_METHOD = (
    "For each chosen day, STAXIS cuts the chosen hours (Indian time) into one-minute steps and, at every step, adds up the concurrent viewers of the channel's live streams in the chosen feed "
    "(All = Primary + Secondary; Primary = the long-running main stream; Secondary = other streams live at the same time). The average is taken over the minutes the channel was live; "
    "the peak is the highest minute. Across days, the daily averages are averaged over the days the channel was live in those hours. Nothing is interpolated."
)
VIEWS_METHOD = (
    "For each chosen day, the views a video gained between the start and the end of the chosen hours (Indian time) = its views measured at the end minus its views measured at the start. "
    "A video uploaded inside the window starts from zero. A video not measured within 2 hours of both ends is left out and counted under coverage. Views are what YouTube reports; they are not TV ratings."
)


def _check(feed: str, scope: str, genre: str | None, start_hour: int, end_hour: int) -> None:
    if feed not in FEEDS:
        raise ValueError("feed must be all, primary or secondary")
    if scope not in SCOPES:
        raise ValueError("content must be live, video, shorts or replay")
    if genre and genre not in GENRES:
        raise ValueError("genre must be one of: " + ", ".join(GENRES))
    if not (0 <= start_hour < 24 and 1 <= end_hour <= 24 and end_hour > start_hour):
        raise ValueError("choose hours like 9 to 12 (Indian time)")


def _fresh_for(*_args: Any, end_date: str = "", **_kwargs: Any) -> float:
    """A report that ends before today is settled (an hour); one that reaches into today can change as each hour completes (two minutes)."""
    try:
        return 3600.0 if parse_day(end_date, "to") < today_ist() else 120.0
    except ValueError:
        return 120.0


@ttl_cache(stale=True, snapshot=_fresh_for)
def build_report(session: Session, *, start_date: str, end_date: str, start_hour: int = 9, end_hour: int = 12, feed: str = "all", scope: str = "live", genre: str | None = None,
                 language: str | None = None, segment: str | None = None, by_genre: bool = False, top: int = 50, channel_ids: list[int] | None = None,
                 target: dict[str, Any] | None = None, profiles: dict[int, dict[str, Any]] | None = None, known_only: bool = False, now: datetime | None = None) -> dict[str, Any]:
    start_day, end_day = parse_day(start_date, "from"), parse_day(end_date, "to")
    start_hour, end_hour = int(start_hour), int(end_hour)
    genre = genre or None
    _check(feed, scope, genre, start_hour, end_hour)
    if end_day < start_day:
        raise ValueError("the end date cannot be before the start date")
    span = (end_day - start_day).days + 1
    if span > MAX_RANGE_DAYS or (scope != "live" and span > MAX_VIEW_DAYS):
        raise ValueError(f"choose at most {MAX_RANGE_DAYS if scope == 'live' else MAX_VIEW_DAYS} days for this kind of report")
    now = utc(now) if now else now_utc()
    days = [start_day + timedelta(days=i) for i in range(span)]
    windows = [(d, *ist_hours(d, start_hour, end_hour)) for d in days]
    windows = [w for w in windows if w[2] <= now]
    base = {"scope": scope, "scope_label": SCOPES[scope], "feed": feed if scope == "live" else None, "genre": genre, "start_hour": start_hour, "end_hour": end_hour,
            "from": start_day.isoformat(), "to": end_day.isoformat(), "timezone": "IST", "filters": {"language": language, "segment": segment, "channel_ids": channel_ids or []}, "target": target,
            "generated_at": now.isoformat(),
            "days_with_data_possible": len(windows)}
    if scope == "live":
        out = _live(session, windows, feed=feed, genre=genre, language=language, segment=segment, by_genre=by_genre, top=top, channel_ids=channel_ids)
        out["method"] = LIVE_METHOD
        value_key = "average"
    else:
        out = _views(session, windows, scope=scope, genre=genre, language=language, segment=segment, by_genre=by_genre, top=top, channel_ids=channel_ids)
        out["method"] = VIEWS_METHOD
        value_key = "views"
    if target and target.get("active"):
        out["rows"] = audience_mod.apply_target(out["rows"], value_key, profiles, target, known_only=known_only)
        out["method"] += " " + TARGET_NOTE
    return {**base, **out}


def _live(session: Session, windows: list, *, feed: str, genre: str | None, language: str | None, segment: str | None, by_genre: bool, top: int, channel_ids: list[int] | None = None) -> dict[str, Any]:
    def collect(topic: str | None) -> dict[int, dict[str, Any]]:
        acc: dict[int, dict[str, Any]] = {}
        for _day, s, e in windows:
            stats = live_window_stats(session, start_at=s, end_at=e, language=language, segment=segment, bucket_seconds=60, topic=topic)
            for row in stats["channels"]:
                if channel_ids and row["channel_id"] not in channel_ids:
                    continue
                a = acc.setdefault(row["channel_id"], {"name": row["name"], "language": row["language"], "segment": row["segment"], "avg": [], "peaks": [], "watch": []})
                stat = row["feeds"][feed]
                if stat["average"] is not None:
                    a["avg"].append(stat["average"])
                    a["peaks"].append(stat["peak"])
                    a["watch"].append(row["watch_hours"][feed])
        return acc

    def rows_of(acc: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        rows = [{"channel_id": cid, "name": a["name"], "language": a["language"], "segment": a["segment"], "average": rnd(mean(a["avg"]), 0), "peak": max(a["peaks"]), "watch_hours": round(sum(a["watch"]), 1), "days_seen": len(a["avg"])}
                for cid, a in acc.items() if a["avg"]]
        rows.sort(key=lambda r: r["average"], reverse=True)
        total = sum(r["average"] for r in rows) or 0
        for rank, r in enumerate(rows, start=1):
            r["rank"] = rank
            r["share_percent"] = rnd(100 * r["average"] / total, 1) if total else None
        return rows

    rows = rows_of(collect(genre))
    genres = []
    if by_genre and not genre:
        for g in GENRES:
            gr = rows_of(collect(g))
            if gr:
                genres.append({"genre": g, "rows": gr[:10], "channels": len(gr)})
    return {"kind": "audience", "rows": rows[:top], "channel_count": len(rows), "by_genre": genres,
            "totals": {"sum_of_channel_averages": sum(r["average"] for r in rows), "highest_peak": max((r["peak"] for r in rows), default=None)},
            "coverage": {"days_requested": len(windows), "channels_seen_live": len(rows)}}


def _views(session: Session, windows: list, *, scope: str, genre: str | None, language: str | None, segment: str | None, by_genre: bool, top: int, channel_ids: list[int] | None = None) -> dict[str, Any]:
    channels, languages = pick_channels(session, segment=segment, language=language, channel_ids=channel_ids)
    by_id = {c.id: c for c in channels}
    ids = list(by_id)
    per_channel: dict[int, dict[str, int]] = defaultdict(lambda: {"views": 0, "videos": 0, "uploads": 0})
    per_genre: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    considered = measured = 0
    for _day, s, e in windows:
        if not ids:
            break
        rows = session.execute(select(Observation, Video).join(Video, Video.id == Observation.video_id).where(
            Observation.channel_id.in_(ids), Observation.observed_at >= s - EDGE, Observation.observed_at <= e, Observation.view_count.is_not(None))
            .order_by(Observation.video_id, Observation.observed_at)).all()
        grouped: dict[int, list[tuple[Observation, Video]]] = defaultdict(list)
        for obs, vid in rows:
            grouped[vid.id].append((obs, vid))
        for series in grouped.values():
            vid = series[0][1]
            topic = vid.topic or "Other"
            last = series[-1][0]
            if not _scope_matches({"classification": last.classification, "is_live": last.is_live}, scope):
                continue
            if genre and topic != genre:
                continue
            considered += 1
            end_obs = next((o for o, _ in reversed(series) if utc(o.observed_at) <= e and utc(o.observed_at) >= e - EDGE), None)
            start_obs = next((o for o, _ in reversed(series) if utc(o.observed_at) <= s), None)
            published = parse_published(vid.published_at)
            new_upload = published is not None and s <= published <= e
            if end_obs is None:
                continue
            if start_obs is not None and utc(start_obs.observed_at) < s - EDGE:
                start_obs = None
            if start_obs is None and not new_upload:
                continue
            gained = max(0, int(end_obs.view_count) - (0 if start_obs is None else int(start_obs.view_count)))
            measured += 1
            row = per_channel[vid.channel_id]
            row["views"] += gained
            row["videos"] += 1
            row["uploads"] += 1 if new_upload else 0
            per_genre[topic][vid.channel_id] += gained
    def ranked(data: dict[int, int | dict]) -> list[dict[str, Any]]:
        out = []
        for cid, v in data.items():
            c = by_id[cid]
            views = v["views"] if isinstance(v, dict) else v
            if views <= 0:
                continue
            out.append({"channel_id": cid, "name": c.name, "language": languages[cid], "segment": c.segment or "news", "views": views,
                        "videos": v["videos"] if isinstance(v, dict) else None, "uploads": v["uploads"] if isinstance(v, dict) else None})
        out.sort(key=lambda r: r["views"], reverse=True)
        total = sum(r["views"] for r in out) or 0
        for rank, r in enumerate(out, start=1):
            r["rank"] = rank
            r["share_percent"] = rnd(100 * r["views"] / total, 1) if total else None
        return out

    rows = ranked(per_channel)
    genres = []
    if by_genre and not genre:
        for g in GENRES:
            gr = ranked(per_genre.get(g, {}))
            if gr:
                genres.append({"genre": g, "rows": gr[:10], "channels": len(gr), "views": sum(r["views"] for r in gr)})
        genres.sort(key=lambda g: g["views"], reverse=True)
    return {"kind": "views", "rows": rows[:top], "channel_count": len(rows), "by_genre": genres, "totals": {"views": sum(r["views"] for r in rows)},
            "coverage": {"videos_matching": considered, "videos_measured_at_both_ends": measured, "videos_left_out": considered - measured,
                         "percent_measured": rnd(100 * measured / considered, 1) if considered else None}}
