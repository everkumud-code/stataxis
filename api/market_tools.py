"""Reports and decision tools built only from what STAXIS has measured: weekly views, prime-time audience, creator scores and a media planner.

Nothing here is invented. Every figure comes from the collected observations, every response says how it was worked out
(`method`), and every row says how much data stands behind it (`coverage`, `confidence`) so a reader can tell a solid number from a thin one.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from api import audience as audience_mod
from api.live_stats import live_window_stats
from api.market_common import (
    IST, ist_hours, ist_window, latest_observations, mean, now_utc, parse_day, parse_published, percentile_rank, pick_channels, rnd, stdev, today_ist, utc,
)
from collector.storage import ChannelStats, Video
from metrics.markets import market_label

PRIME_SLOTS = [(17, 18), (18, 19), (19, 20), (20, 21), (21, 22), (22, 23)]
STALE_AFTER = timedelta(hours=12)

WEEKLY_METHOD = (
    "Views of every video uploaded in the chosen dates (Indian time), as last measured by STAXIS, added up per channel; share is the channel's part of its group. "
    "A video only counts once STAXIS has seen it, and its views are as of the last time it was measured (videos not measured in the last 12 hours are counted as 'stale')."
)
PRIME_METHOD = (
    "For every chosen day and every one-hour slot, STAXIS works out each channel's average concurrent live viewers on a one-minute grid (all live streams of the channel together), "
    "then averages those day figures over the days the channel was seen live in that slot. Nothing is interpolated and a slot with no live stream is left out, not counted as zero."
)


def _videos_in(session: Session, channel_ids: list[int], start: datetime, end: datetime) -> list[Video]:
    out: list[Video] = []
    if not channel_ids:
        return out
    for video in session.query(Video).filter(Video.channel_id.in_(channel_ids), Video.published_at.is_not(None)).all():
        moment = parse_published(video.published_at)
        if moment is not None and start <= moment < end:
            out.append(video)
    return out


# --------------------------------------------------------------------------------------------- weekly views
def weekly_views(session: Session, *, start_date: str, end_date: str, segment: str | None = None, language: str | None = None, channel_ids: list[int] | None = None,
                 target: dict[str, Any] | None = None, profiles: dict[int, dict[str, Any]] | None = None, known_only: bool = False, now: datetime | None = None) -> dict[str, Any]:
    start_day, end_day = parse_day(start_date, "from"), parse_day(end_date, "to")
    start, end = ist_window(start_day, end_day)
    now = utc(now) if now else now_utc()
    channels, languages = pick_channels(session, segment=segment, language=language, channel_ids=channel_ids)
    by_id = {c.id: c for c in channels}
    videos = _videos_in(session, list(by_id), start, end)
    latest = latest_observations(session, [v.id for v in videos])
    per: dict[int, dict[str, Any]] = {c.id: {"videos": 0, "measured": 0, "views": 0, "stale": 0, "likes": 0, "comments": 0} for c in channels}
    for video in videos:
        row = per[video.channel_id]
        row["videos"] += 1
        obs = latest.get(video.id)
        if obs is None or obs.view_count is None:
            continue
        row["measured"] += 1
        row["views"] += int(obs.view_count)
        row["likes"] += int(obs.like_count or 0)
        row["comments"] += int(obs.comment_count or 0)
        if now - utc(obs.observed_at) > STALE_AFTER:
            row["stale"] += 1
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for channel in channels:
        row = per[channel.id]
        if not row["videos"]:
            continue
        label = market_label(channel.segment, languages[channel.id])
        groups[label].append({
            "channel_id": channel.id, "name": channel.name, "segment": channel.segment or "news", "language": languages[channel.id],
            "videos": row["videos"], "measured_videos": row["measured"], "views": row["views"], "stale_videos": row["stale"],
            "coverage_percent": rnd(100 * row["measured"] / row["videos"]) if row["videos"] else None,
            "engagement_percent": rnd(100 * (row["likes"] + row["comments"]) / row["views"], 2) if row["views"] else None,
        })
    out_groups = []
    for label, items in groups.items():
        total = sum(i["views"] for i in items)
        items.sort(key=lambda i: i["views"], reverse=True)
        for rank, item in enumerate(items, start=1):
            item["rank"] = rank
            item["share_percent"] = rnd(100 * item["views"] / total, 1) if total else None
        items = audience_mod.apply_target(items, "views", profiles, target, known_only=known_only)
        out_groups.append({"label": label, "channel_count": len(items), "total_views": total, "channels": items})
    out_groups.sort(key=lambda g: g["total_views"], reverse=True)
    return {"from": start_day.isoformat(), "to": end_day.isoformat(), "timezone": "IST", "filters": {"segment": segment, "language": language, "channel_ids": channel_ids or []}, "target": target,
            "method": WEEKLY_METHOD + (TARGET_METHOD if target and target.get("active") else ""), "generated_at": now.isoformat(), "groups": out_groups}


# --------------------------------------------------------------------------------------------- prime time
def prime_time(session: Session, *, start_date: str, end_date: str, language: str | None = None, segment: str | None = None, channel_ids: list[int] | None = None,
               target: dict[str, Any] | None = None, profiles: dict[int, dict[str, Any]] | None = None, known_only: bool = False,
               slots: list[tuple[int, int]] | None = None, top: int = 5, now: datetime | None = None) -> dict[str, Any]:
    start_day, end_day = parse_day(start_date, "from"), parse_day(end_date, "to")
    now = utc(now) if now else now_utc()
    ist_window(start_day, end_day)  # validates the range
    slots = slots or PRIME_SLOTS
    days = [start_day + timedelta(days=i) for i in range((end_day - start_day).days + 1)]
    out_slots = []
    for s_hour, e_hour in slots:
        acc: dict[int, dict[str, Any]] = {}
        for day in days:
            s, e = ist_hours(day, s_hour, e_hour)
            if e > now:
                continue
            stats = live_window_stats(session, start_at=s, end_at=e, language=language, segment=segment, bucket_seconds=60)
            for row in stats["channels"]:
                if channel_ids and row["channel_id"] not in channel_ids:
                    continue
                a = acc.setdefault(row["channel_id"], {"name": row["name"], "language": row["language"], "segment": row["segment"], "avg": [], "primary": [], "peaks": []})
                a["avg"].append(row["feeds"]["all"]["average"])
                a["primary"].append(row["feeds"]["primary"]["average"])
                a["peaks"].append(row["feeds"]["all"]["peak"])
        rows = []
        for channel_id, a in acc.items():
            avg = mean([v for v in a["avg"] if v is not None])
            if avg is None:
                continue
            rows.append({"channel_id": channel_id, "name": a["name"], "language": a["language"], "segment": a["segment"], "average_concurrent": rnd(avg, 0),
                         "primary_average": rnd(mean([v for v in a["primary"] if v is not None]), 0), "peak_concurrent": max(p for p in a["peaks"] if p is not None),
                         "days_seen": len(a["avg"]), "days_in_range": len(days)})
        rows.sort(key=lambda r: r["average_concurrent"], reverse=True)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        rows = audience_mod.apply_target(rows, "average_concurrent", profiles, target, known_only=known_only)
        out_slots.append({"slot": f"{s_hour:02d}:00-{e_hour:02d}:00", "start_hour": s_hour, "end_hour": e_hour, "top": rows[:top], "channels": rows})
    return {"from": start_day.isoformat(), "to": end_day.isoformat(), "timezone": "IST", "filters": {"language": language, "segment": segment, "channel_ids": channel_ids or []}, "target": target,
            "method": PRIME_METHOD + (TARGET_METHOD if target and target.get("active") else ""), "slots": out_slots}


# --------------------------------------------------------------------------------------------- creator score
CREATOR_WEIGHTS = {"reach": 0.20, "pull": 0.30, "engagement": 0.25, "consistency": 0.15, "growth": 0.10}
CREATOR_METHOD = (
    "Score 0-100 from five measured parts, each ranked against the other channels in the same comparison: reach (subscribers), pull (average views of a recent video as a share of subscribers), "
    "engagement ((likes + comments) / views), consistency (how many recent uploads, spread over how many days) and growth (change in subscribers over the window, only when STAXIS has at least 3 days of history). "
    "A part STAXIS cannot measure is left out and the others are re-weighted. Confidence says how much data stands behind the score."
)


def _subscribers(session: Session, channel_ids: list[int], since: datetime) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    if not channel_ids:
        return out
    rows = session.query(ChannelStats).filter(ChannelStats.channel_id.in_(channel_ids)).order_by(ChannelStats.channel_id, ChannelStats.observed_at).all()
    for r in rows:
        d = out.setdefault(r.channel_id, {"first": None, "last": None})
        if r.subscribers is not None:
            if d["first"] is None and utc(r.observed_at) >= since:
                d["first"] = (utc(r.observed_at), int(r.subscribers))
            d["last"] = (utc(r.observed_at), int(r.subscribers))
    return out


def creator_scores(session: Session, *, segment: str | None = None, language: str | None = None, days: int = 30, channel_ids: list[int] | None = None, now: datetime | None = None) -> dict[str, Any]:
    if not 7 <= int(days) <= 90:
        raise ValueError("days must be between 7 and 90")
    days = int(days)
    now = utc(now) if now else now_utc()
    since = now - timedelta(days=days)
    channels, languages = pick_channels(session, segment=segment, language=language, channel_ids=channel_ids)
    ids = [c.id for c in channels]
    subs = _subscribers(session, ids, since)
    videos = _videos_in(session, ids, since, now + timedelta(days=1))
    latest = latest_observations(session, [v.id for v in videos])
    per_channel: dict[int, list[Video]] = defaultdict(list)
    for v in videos:
        per_channel[v.channel_id].append(v)
    raw: dict[int, dict[str, Any]] = {}
    for c in channels:
        views, likes, comments, count, active_days = [], 0, 0, 0, set()
        for v in per_channel.get(c.id, []):
            obs = latest.get(v.id)
            moment = parse_published(v.published_at)
            if moment:
                active_days.add(moment.astimezone(IST).date())
            if obs is None or obs.view_count is None:
                continue
            count += 1
            views.append(int(obs.view_count))
            likes += int(obs.like_count or 0)
            comments += int(obs.comment_count or 0)
        s = subs.get(c.id) or {}
        last_subs = s["last"][1] if s.get("last") else None
        history_days = (s["last"][0] - s["first"][0]).total_seconds() / 86400 if s.get("first") and s.get("last") else 0.0
        raw[c.id] = {
            "subscribers": last_subs,
            "videos": count,
            "avg_views": mean(views),
            "pull": (mean(views) / last_subs) if views and last_subs else None,
            "engagement": ((likes + comments) / sum(views)) if views and sum(views) > 0 else None,
            "uploads_per_week": len(per_channel.get(c.id, [])) / (days / 7),
            "active_days": len(active_days),
            "growth": ((s["last"][1] - s["first"][1]) / s["first"][1]) if history_days >= 3 and s.get("first") and s["first"][1] else None,
            "history_days": history_days,
        }
    rows = []
    peers = {k: [r[k] for r in raw.values() if r[k] is not None] for k in ("subscribers", "pull", "engagement", "uploads_per_week", "growth")}
    for c in channels:
        r = raw[c.id]
        parts: dict[str, float] = {}
        for part, key in (("reach", "subscribers"), ("pull", "pull"), ("engagement", "engagement"), ("consistency", "uploads_per_week"), ("growth", "growth")):
            if r[key] is not None and len(peers[key]) >= 3:
                parts[part] = percentile_rank(r[key], peers[key])
        weight = sum(CREATOR_WEIGHTS[p] for p in parts)
        score = sum(CREATOR_WEIGHTS[p] * parts[p] for p in parts) / weight if weight else None
        videos_factor = min(1.0, r["videos"] / 8)
        confidence = round(100 * (0.5 * videos_factor + 0.2 * (1 if r["subscribers"] else 0) + 0.3 * min(1.0, r["history_days"] / 14)))
        rows.append({
            "channel_id": c.id, "name": c.name, "segment": c.segment or "news", "language": languages[c.id], "score": rnd(score), "parts": {k: rnd(v) for k, v in parts.items()},
            "subscribers": r["subscribers"], "videos_measured": r["videos"], "average_views": rnd(r["avg_views"], 0), "pull_percent": rnd(r["pull"] * 100, 1) if r["pull"] is not None else None,
            "engagement_percent": rnd(r["engagement"] * 100, 2) if r["engagement"] is not None else None, "uploads_per_week": rnd(r["uploads_per_week"], 1),
            "active_days": r["active_days"], "growth_percent": rnd(r["growth"] * 100, 2) if r["growth"] is not None else None,
            "confidence": confidence, "confidence_label": "high" if confidence >= 70 else "medium" if confidence >= 40 else "low",
        })
    rows.sort(key=lambda x: (x["score"] is not None, x["score"] or 0), reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    note = None if len(channels) >= 4 else "Fewer than 4 channels are being compared, so the parts that need peers could not be ranked."
    return {"days": days, "filters": {"segment": segment, "language": language}, "method": CREATOR_METHOD, "weights": CREATOR_WEIGHTS, "note": note, "channels": rows}


# --------------------------------------------------------------------------------------------- media planner
PLANNER_METHOD = (
    "For the chosen hours (Indian time) on each of the last full days, STAXIS works out every channel's average concurrent live viewers (one-minute grid). "
    "Average is the mean of the daily averages over the days the channel was live in that window; stability compares day to day (100 = identical every day). "
    "Cost per 1,000 live viewers = the rate you typed for one spot / (average concurrent viewers / 1,000). This is the audience watching at the same moment per insertion, "
    "not unique reach and not delivered impressions, and audiences of different channels overlap by an amount STAXIS cannot see."
)


def media_plan(session: Session, *, start_hour: int, end_hour: int, days: int = 7, language: str | None = None, segment: str | None = None,
               rates: dict[int, float] | None = None, budget: float | None = None, max_share: float = 0.4, authenticity: dict[int, dict[str, Any]] | None = None,
               target: dict[str, Any] | None = None, profiles: dict[int, dict[str, Any]] | None = None, channel_ids: list[int] | None = None, now: datetime | None = None) -> dict[str, Any]:
    if not (0 <= int(start_hour) < 24 and 1 <= int(end_hour) <= 24 and int(end_hour) > int(start_hour)):
        raise ValueError("choose hours like 20 to 22 (Indian time)")
    if int(end_hour) - int(start_hour) > 12:
        raise ValueError("choose a window of at most 12 hours")
    if not 3 <= int(days) <= 28:
        raise ValueError("days must be between 3 and 28")
    start_hour, end_hour, days = int(start_hour), int(end_hour), int(days)
    now = utc(now) if now else now_utc()
    rates = {int(k): float(v) for k, v in (rates or {}).items() if v not in (None, "") and float(v) > 0}
    target = target or {}
    t_ages = [a for a in (target.get("ages") or [])]
    t_states = [s for s in (target.get("states") or [])]
    t_gender = str(target.get("gender") or "")
    if any(a not in audience_mod.AGE_BANDS for a in t_ages):
        raise ValueError("target age must be among: " + ", ".join(audience_mod.AGE_BANDS))
    if any(s not in audience_mod.STATES for s in t_states):
        raise ValueError("target states must be Indian states or union territories")
    if t_gender and t_gender not in audience_mod.GENDERS:
        raise ValueError("target gender must be male, female or other")
    targeted = bool(t_ages or t_states or t_gender)
    if budget is not None and float(budget) <= 0:
        raise ValueError("the budget must be more than zero")
    last_day = today_ist(now) - timedelta(days=1)
    day_list = [last_day - timedelta(days=i) for i in range(days)][::-1]
    acc: dict[int, dict[str, Any]] = {}
    for day in day_list:
        s, e = ist_hours(day, start_hour, end_hour)
        stats = live_window_stats(session, start_at=s, end_at=e, language=language, segment=segment, bucket_seconds=60)
        for row in stats["channels"]:
            if channel_ids and row["channel_id"] not in channel_ids:
                continue
            a = acc.setdefault(row["channel_id"], {"name": row["name"], "language": row["language"], "segment": row["segment"], "avg": [], "primary": [], "peaks": []})
            if row["feeds"]["all"]["average"] is not None:
                a["avg"].append(row["feeds"]["all"]["average"])
                a["primary"].append(row["feeds"]["primary"]["average"])
                a["peaks"].append(row["feeds"]["all"]["peak"])
    rows = []
    for channel_id, a in acc.items():
        if not a["avg"]:
            continue
        avg = mean(a["avg"])
        sd = stdev(a["avg"])
        stability = round(100 * (1 - min(1.0, (sd / avg))), 0) if sd is not None and avg else None
        half = len(a["avg"]) // 2
        trend = None
        if len(a["avg"]) >= 4 and mean(a["avg"][:half]):
            trend = rnd(100 * (mean(a["avg"][half:]) - mean(a["avg"][:half])) / mean(a["avg"][:half]), 1)
        rate = rates.get(channel_id)
        auth = (authenticity or {}).get(channel_id) or {}
        fit = audience_mod.match((profiles or {}).get(channel_id), ages=t_ages, states=t_states, gender=t_gender) if targeted else None
        matched = avg * fit["share"] if fit else None
        rows.append({
            "channel_id": channel_id, "name": a["name"], "language": a["language"], "segment": a["segment"], "average_concurrent": rnd(avg, 0),
            "primary_average": rnd(mean([v for v in a["primary"] if v is not None]), 0), "peak_concurrent": max(p for p in a["peaks"] if p is not None),
            "days_seen": len(a["avg"]), "days_in_range": days, "stability": stability, "trend_percent": trend,
            "rate": rate, "cost_per_1000": rnd(rate / (avg / 1000), 0) if rate and avg else None,
            "audience_known": fit is not None, "audience_match": fit, "matched_audience": rnd(matched, 0) if matched is not None else None,
            "cost_per_1000_matched": rnd(rate / (matched / 1000), 0) if rate and matched else None,
            "authenticity_risk": auth.get("risk", "not_checked"), "authenticity_signals": auth.get("signals", []),
            "confidence_label": "high" if len(a["avg"]) >= max(5, days * 0.7) else "medium" if len(a["avg"]) >= 3 else "low",
        })
    rows.sort(key=lambda r: r["average_concurrent"], reverse=True)
    total = sum(r["average_concurrent"] for r in rows) or 0
    cost_key = "cost_per_1000_matched" if targeted else "cost_per_1000"
    costs = sorted(r[cost_key] for r in rows if r[cost_key])
    median_cost = costs[len(costs) // 2] if costs else None
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
        row["audience_share_percent"] = rnd(100 * row["average_concurrent"] / total, 1) if total else None
        row["value_index"] = round(100 * median_cost / row[cost_key]) if median_cost and row[cost_key] else None
    plan = _split_budget(rows, float(budget), max_share, targeted) if budget and rates else None
    return {"window": {"start_hour": start_hour, "end_hour": end_hour, "days": [d.isoformat() for d in day_list], "timezone": "IST"}, "filters": {"language": language, "segment": segment},
            "method": PLANNER_METHOD + (TARGET_METHOD if targeted else ""), "median_cost_per_1000": median_cost, "channels": rows, "plan": plan,
            "target": {"ages": t_ages, "states": t_states, "gender": t_gender or None, "active": targeted, "channels_with_audience_data": sum(1 for r in rows if r["audience_known"])}}


def _split_budget(rows: list[dict[str, Any]], budget: float, max_share: float, targeted: bool = False) -> dict[str, Any]:
    """Buy whole spots, best audience per rupee first, never more than max_share of the budget on one channel and never on a channel flagged high risk.
    With a target audience, only channels whose audience is known are bought and the audience counted is the part that matches the target."""
    def audience(r: dict[str, Any]) -> float:
        return (r["matched_audience"] or 0) if targeted else r["average_concurrent"]
    pool = [r for r in rows if r["rate"] and audience(r) and r["authenticity_risk"] != "high"]
    pool.sort(key=lambda r: audience(r) / r["rate"], reverse=True)
    cap = budget * max(0.1, min(1.0, max_share))
    spent, buys = 0.0, {r["channel_id"]: 0 for r in pool}
    progress = True
    while progress:
        progress = False
        for r in pool:
            cost = r["rate"]
            if spent + cost <= budget + 1e-9 and (buys[r["channel_id"]] + 1) * cost <= cap + 1e-9:
                buys[r["channel_id"]] += 1
                spent += cost
                progress = True
    lines = [{"channel_id": r["channel_id"], "name": r["name"], "spots": buys[r["channel_id"]], "rate": r["rate"], "spend": round(buys[r["channel_id"]] * r["rate"], 2),
              "average_concurrent": audience(r), "live_viewers_per_insertion": audience(r) * buys[r["channel_id"]]} for r in pool if buys[r["channel_id"]]]
    exposure = sum(line["live_viewers_per_insertion"] for line in lines)
    skipped = [r["name"] for r in rows if r["rate"] and r["authenticity_risk"] == "high"]
    no_audience = [r["name"] for r in rows if targeted and r["rate"] and not r["audience_known"]]
    return {"budget": budget, "spent": round(spent, 2), "left": round(budget - spent, 2), "max_share_percent": round(100 * max_share), "lines": lines,
            "total_spots": sum(line["spots"] for line in lines), "live_viewers_across_spots": exposure,
            "blended_cost_per_1000": round(spent / (exposure / 1000), 0) if exposure else None, "skipped_high_risk": skipped, "skipped_no_audience_data": no_audience, "counts_matched_audience_only": targeted,
            "note": "Estimate for comparing options. Live viewers across spots adds the audience watching at each insertion; the same person may be counted more than once."}


TARGET_METHOD = (
    " With a target audience, each channel's average is multiplied by the share of its audience inside the target (age, states, gender combined as if independent), taken from the audience "
    "profile the channel or a named study supplied. A channel without a profile is not guessed: it is marked 'no audience data' and left out of the budget split."
)


def quota_need(channel_count: int, collect_seconds: int, live_poll_seconds: int, live_streams: int | None = None) -> dict[str, Any]:
    """What the YouTube quota has to be for the channels and cadence you want (the number to put in a quota-increase request)."""
    from collector.quota_estimate import daily_quota_units, estimate_daily_units
    est = estimate_daily_units(channel_count, collect_seconds, live_poll_seconds, live_streams)
    quota = daily_quota_units()
    need = math.ceil(est["total"] / 0.85 / 1000) * 1000
    return {"channels": channel_count, "collect_seconds": collect_seconds, "live_poll_seconds": live_poll_seconds, "units_per_day": est, "current_quota": quota,
            "fits": est["total"] <= quota * 0.9, "quota_to_request": max(need, quota), "headroom_percent": 15}
