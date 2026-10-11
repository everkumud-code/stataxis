"""Live event compare: up to 30 channels covering the same live event, side by side on one live screen, with the audience each has right now, how it moved, its peak,
the STX index and the tone of what each is broadcasting.

Which channels are "covering the event": the reader either picks the channels, or gives words that describe the event (for example "budget") and STAXIS takes every channel that is live now
with a stream whose title contains one of them. Nothing is guessed: a channel that is not live is listed as not live.

Tone is read from the titles of the live streams with the same plain word lists the rest of STAXIS uses. It is indicative: it says whether the words on the screen are positive, negative
or mixed, not how the audience feels (STAXIS cannot read live chat). Every row shows how many of its words were recognised so a thin reading is not mistaken for a strong one.
"""

from __future__ import annotations

from api.ttl_cache import ttl_cache

from datetime import datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy.orm import Session

from api.insight_extensions import _sentiment
from api.live_stats import FRESHNESS_SECONDS, _load_streams
from api.market_common import now_utc, pick_channels, rnd, utc
from api.media_intelligence import market_report
from collector.storage import Video

MAX_CHANNELS = 30
METHOD = (
    "Every minute, each channel's live viewers are the latest sample of each of its live streams (a sample older than 3 minutes is not used) added together. 'Now' is the latest minute, "
    "'change' compares it with five minutes earlier, 'peak' and 'average' are over the chosen window (the average only over minutes the channel was live). "
    "STX is the channel's STX index for the chosen period. Tone comes from the words in the live stream titles (positive / negative word lists, indicative only, not audience sentiment)."
)


def _series(samples: list[tuple[datetime, int]], grid: list[datetime]) -> list[int | None]:
    out: list[int | None] = []
    i, latest = 0, None
    for t in grid:
        while i < len(samples) and samples[i][0] <= t:
            latest = samples[i]
            i += 1
        out.append(latest[1] if latest and (t - latest[0]).total_seconds() <= FRESHNESS_SECONDS else None)
    return out


@ttl_cache(scale=0.2)   # a live screen: a few seconds is enough
def live_event_compare(session: Session, *, terms: list[str] | None = None, channel_ids: list[int] | None = None, minutes: int = 60, segment: str | None = None, language: str | None = None,
                       stx_period: str = "7d", now: datetime | None = None) -> dict[str, Any]:
    if not 10 <= int(minutes) <= 180:
        raise ValueError("minutes must be between 10 and 180")
    minutes = int(minutes)
    terms = [t.strip().casefold() for t in (terms or []) if t and t.strip()][:8]
    if channel_ids and len(set(channel_ids)) > MAX_CHANNELS:
        raise ValueError(f"compare at most {MAX_CHANNELS} channels at a time")
    now = utc(now) if now else now_utc()
    start = now - timedelta(minutes=minutes)
    channels, languages = pick_channels(session, segment=segment, language=language, channel_ids=channel_ids)
    by_id = {c.id: c for c in channels}
    streams, _, _ = _load_streams(session, start_at=start, end_at=now, language=None, segment=None)
    titles: dict[str, tuple[str, datetime | None]] = {}
    stream_ids = [vid for cid, ss in streams.items() if cid in by_id for vid in ss]
    for i in range(0, len(stream_ids), 400):
        for v in session.query(Video).filter(Video.youtube_video_id.in_(stream_ids[i:i + 400])).all():
            titles[v.youtube_video_id] = (v.title or "", utc(v.live_started_at) if v.live_started_at else None)
    grid = [start + timedelta(minutes=m) for m in range(minutes + 1)]
    explicit = bool(channel_ids)
    rows: list[dict[str, Any]] = []
    for cid, ss in streams.items():
        c = by_id.get(cid)
        if c is None:
            continue
        live_ss = {vid: s for vid, s in ss.items() if s.samples and (now - s.samples[-1][0]).total_seconds() <= FRESHNESS_SECONDS}
        matched = {vid: s for vid, s in live_ss.items() if not terms or any(t in titles.get(vid, ("", None))[0].casefold() for t in terms)}
        counted = matched if (terms and not explicit) else live_ss if explicit or not terms else matched
        if terms and not explicit and not matched:
            continue
        if not counted:
            continue
        per_stream = [_series(sorted(s.samples), grid) for s in counted.values()]
        total = [sum(v for v in col if v is not None) if any(v is not None for v in col) else None for col in zip(*per_stream)]
        live_values = [v for v in total if v is not None]
        if not live_values or total[-1] is None:
            continue
        now_v = total[-1]
        ago = total[-6] if len(total) >= 6 else None
        lead_id = max(counted, key=lambda vid: counted[vid].samples[-1][1])
        tones = [_sentiment(titles.get(vid, ("", None))[0]) for vid in counted]
        score = sum(t["score"] * max(counted[vid].samples[-1][1], 1) for t, vid in zip(tones, counted)) / sum(max(counted[vid].samples[-1][1], 1) for vid in counted)
        coverage = sum(t["lexical_coverage"] for t in tones) / len(tones)
        starts = [titles[vid][1] for vid in counted if vid in titles and titles[vid][1]]
        rows.append({
            "channel_id": cid, "name": c.name, "segment": c.segment or "news", "language": languages[cid], "live_now": now_v, "average": rnd(sum(live_values) / len(live_values), 0), "peak": max(live_values),
            "change_5m_percent": rnd(100 * (now_v - ago) / ago, 1) if ago else None, "streams": len(counted), "lead_title": titles.get(lead_id, ("", None))[0][:140],
            "live_for_minutes": round((now - min(starts)).total_seconds() / 60) if starts else None, "minutes_live_in_window": len(live_values),
            "matches_event": bool(matched) if terms else None,
            "tone": {"label": "positive" if score > 0.15 else "negative" if score < -0.15 else "mixed/neutral", "score": rnd(score, 2), "words_recognised": rnd(coverage, 2)},
            "series": [v for v in total[-31:]],
        })
    rows.sort(key=lambda r: r["live_now"], reverse=True)
    rows = rows[:MAX_CHANNELS]
    stx_by: dict[int, dict[str, Any]] = {}
    if rows:
        report = market_report(session, as_of=now, period=stx_period, stream_scope="all", limit=200)
        stx_by = {r["channel_id"]: r["stx"] for r in report["channels"]}
    total_now = sum(r["live_now"] for r in rows)
    for rank, r in enumerate(rows, start=1):
        r["rank"] = rank
        r["share_percent"] = rnd(100 * r["live_now"] / total_now, 1) if total_now else None
        x = stx_by.get(r["channel_id"]) or {}
        shown = x.get("display_score") if x.get("display_score") is not None else x.get("score")
        r["stx"] = {"score": rnd(shown), "confidence": x.get("confidence"), "preliminary": bool(x.get("preliminary"))} if shown is not None else None
    not_live = [c.name for c in channels if c.id not in {r["channel_id"] for r in rows}] if explicit else []
    mix = {"positive": 0, "negative": 0, "mixed/neutral": 0}
    for r in rows:
        mix[r["tone"]["label"]] += 1
    weighted = sum(r["tone"]["score"] * r["live_now"] for r in rows) / total_now if total_now else None
    stx_rows = [r for r in rows if r["stx"]]
    return {"as_of": now.isoformat(), "window_minutes": minutes, "stx_period": stx_period, "filters": {"terms": terms, "channel_ids": channel_ids or [], "segment": segment, "language": language},
            "method": METHOD, "summary": {"channels_live": len(rows), "total_live_now": total_now, "leader": rows[0]["name"] if rows else None, "leader_share_percent": rows[0]["share_percent"] if rows else None,
                                         "median_live_now": median([r["live_now"] for r in rows]) if rows else None, "tone_mix": mix, "audience_weighted_tone": rnd(weighted, 2),
                                         "best_stx": max(stx_rows, key=lambda r: r["stx"]["score"])["name"] if stx_rows else None},
            "channels": rows, "not_live": not_live,
            "note": None if rows else ("No channel is live now with a stream matching these words." if terms and not explicit else "None of these channels is live right now.")}
