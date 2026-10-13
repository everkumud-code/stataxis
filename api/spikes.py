"""Spikes (what lifted a channel's audience, and which stream did it) and audience movement (who gained while who lost, in the same minutes).

Both are worked out from the same one-minute grid as the live screens, so they agree with them. They describe what the numbers did; they do not follow any individual viewer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.live_stats import _channel_series, _grid, _load_streams, live_window_stats
from api.ttl_cache import ttl_cache
from collector.storage import Video
from metrics.feeds import min_primary_hours

IST = timedelta(hours=5, minutes=30)
LOOKBACK = 15        # minutes of history a spike is measured against
MIN_RISE = 1500      # viewers: smaller jumps are noise
FACTOR = 1.5         # a spike is at least this many times the recent level
PEAK_WITHIN = 30     # minutes in which the top of the rise is looked for
MOVEMENT_NOTE = (
    "Net movement of each channel's average live viewers between two consecutive windows. Where one channel gained about as much as others lost in the same minutes, the matched shift is shown as a likely "
    "movement of attention; it is an estimate from totals and does not follow any individual viewer. A channel starting or ending a stream also moves the numbers."
)


def _ist(moment: datetime) -> str:
    t = (moment + IST)
    return f"{t.day} {t:%b}, {t.hour % 12 or 12}:{t:%M} {'AM' if t.hour < 12 else 'PM'} IST"


def _minute(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).replace(second=0, microsecond=0)


@ttl_cache(stale=True)
def spikes(session: Session, *, hours: int = 6, language: str | None = None, segment: str | None = None, top: int = 20, now: datetime | None = None) -> dict[str, Any]:
    """Sudden rises in a channel's live audience in the last ``hours`` hours, each with the stream that carried most of the rise."""
    hours = max(1, min(int(hours), 24))
    end = _minute(now)
    start = end - timedelta(hours=hours)
    grid = _grid(start, end, 60)
    streams, channels, _languages = _load_streams(session, start_at=start, end_at=end, language=language, segment=segment)
    threshold = min_primary_hours()
    found: list[dict[str, Any]] = []
    for channel_id, channel_streams in streams.items():
        series = _channel_series(channel_streams, grid, threshold)
        totals = [entry[1].all if entry else None for entry in series]
        i = LOOKBACK
        while i < len(totals):
            now_value = totals[i]
            recent = [v for v in totals[i - LOOKBACK:i] if v is not None]
            if now_value is None or len(recent) < 8:
                i += 1
                continue
            base = median(recent)
            if base <= 0 or now_value < max(FACTOR * base, base + MIN_RISE):
                i += 1
                continue
            window = [(j, totals[j]) for j in range(i, min(len(totals), i + PEAK_WITHIN + 1)) if totals[j] is not None]
            peak_index, peak_value = max(window, key=lambda item: item[1])
            before = series[max(0, i - 5)][2] if series[max(0, i - 5)] else {}
            at_peak = series[peak_index][2] if series[peak_index] else {}
            added = {video_id: viewers - before.get(video_id, 0) for video_id, viewers in at_peak.items()}
            lead_id = max(added, key=added.get) if added else None
            rise = peak_value - base
            found.append({
                "channel_id": channel_id, "channel": channels[channel_id].name, "started_at": grid[i].isoformat(), "started_ist": _ist(grid[i]), "peak_at": grid[peak_index].isoformat(),
                "before": round(base), "peak": peak_value, "rise": round(rise), "minutes_to_peak": peak_index - i,
                "lead_stream": ({"video_id": lead_id, "added": max(0, added[lead_id]), "share_of_rise_percent": round(min(100.0, max(0.0, 100.0 * added[lead_id] / rise)), 0) if rise > 0 else None,
                                 "was_new": lead_id not in before} if lead_id else None),
                "streams_live": len(at_peak),
            })
            i = peak_index + LOOKBACK   # one spike is one story: do not count its shoulders again
    found.sort(key=lambda row: row["rise"], reverse=True)
    found = found[: max(1, min(int(top), 50))]
    ids = {row["lead_stream"]["video_id"] for row in found if row["lead_stream"]}
    titles = {vid: title for vid, title in session.execute(select(Video.youtube_video_id, Video.title).where(Video.youtube_video_id.in_(list(ids)))).all()} if ids else {}
    for row in found:
        lead = row["lead_stream"]
        if lead:
            lead["title"] = titles.get(lead["video_id"])
            share = f", {lead['share_of_rise_percent']:.0f}% of the rise" if lead["share_of_rise_percent"] is not None else ""
            new = " (a stream that had just started)" if lead["was_new"] else ""
            row["text"] = f"{row['channel']} rose from about {row['before']:,} to {row['peak']:,} viewers in {row['minutes_to_peak']} minutes from {row['started_ist']}. Most of it came from “{lead['title'] or lead['video_id']}”{new}{share}."
        else:
            row["text"] = f"{row['channel']} rose from about {row['before']:,} to {row['peak']:,} viewers from {row['started_ist']}."
    return {"hours": hours, "window": {"from": start.isoformat(), "to": end.isoformat()}, "rule": f"A rise of at least {FACTOR:g} times the level of the previous {LOOKBACK} minutes and at least {MIN_RISE:,} viewers.", "spikes": found,
            "note": "A spike shows where the audience rose and which stream carried it; it does not say why viewers came."}


@ttl_cache(stale=True)
def movement(session: Session, *, minutes: int = 30, language: str | None = None, segment: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Who gained and who lost between the last ``minutes`` minutes and the ``minutes`` before them, and the matched shift between them."""
    minutes = max(10, min(int(minutes), 360))
    end = _minute(now)
    mid, start = end - timedelta(minutes=minutes), end - timedelta(minutes=2 * minutes)
    def averages(a: datetime, b: datetime) -> dict[int, tuple[str, float]]:
        stats = live_window_stats(session, start_at=a, end_at=b, language=language, segment=segment, bucket_seconds=60)
        return {row["channel_id"]: (row["name"], row["feeds"]["all"]["average"] or 0.0) for row in stats["channels"]}
    before, after = averages(start, mid), averages(mid, end)
    rows = []
    for channel_id in set(before) | set(after):
        name = (after.get(channel_id) or before.get(channel_id))[0]
        was, now_v = before.get(channel_id, (name, 0.0))[1], after.get(channel_id, (name, 0.0))[1]
        rows.append({"channel_id": channel_id, "channel": name, "before": round(was), "after": round(now_v), "change": round(now_v - was), "change_percent": round(100.0 * (now_v - was) / was, 1) if was > 0 else None})
    gains = [r for r in rows if r["change"] > 0]
    losses = [r for r in rows if r["change"] < 0]
    gained, lost = sum(r["change"] for r in gains), -sum(r["change"] for r in losses)
    matched = min(gained, lost)
    shifts = []
    if matched > 0:
        for loser in losses:
            for gainer in gains:
                amount = matched * (-loser["change"] / lost) * (gainer["change"] / gained)
                if amount >= 50:
                    shifts.append({"from": loser["channel"], "to": gainer["channel"], "viewers": round(amount)})
        shifts.sort(key=lambda s: s["viewers"], reverse=True)
    rows.sort(key=lambda r: r["change"], reverse=True)
    return {"minutes": minutes, "windows": {"before": [start.isoformat(), mid.isoformat()], "after": [mid.isoformat(), end.isoformat()]}, "channels": rows, "gained_total": round(gained), "lost_total": round(lost),
            "matched_shift": round(matched), "shifts": shifts[:12], "note": MOVEMENT_NOTE}
