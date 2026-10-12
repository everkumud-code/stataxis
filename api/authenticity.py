"""Authenticity radar: finds viewership that looks unusual, so a person can look at it.

Public data can show a *pattern*; it can never prove that views or viewers are bought or automated. So the radar never says "fake". It says "unusual", shows the numbers
behind every flag, and keeps an admin's decision (cleared / watching / confirmed) next to it. Signals:

  low_engagement      likes per view far below comparable channels
  views_vs_audience   views per subscriber far above comparable channels
  view_burst          a sudden surge of views that brings almost no new likes
  live_spike          concurrent viewers jump several times above the recent level and drop back within minutes
  live_flatline       a long live stream whose viewer count hardly moves (real audiences move)
  mechanical_steps    views growing by exactly the same amount sample after sample
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.ttl_cache import ttl_cache
from api.market_common import channel_videos, latest_observations, mean, now_utc, parse_published, pick_channels, robust_z, rnd, stdev, utc
from collector.storage import AuthenticityReview, Observation, Video

SIGNALS = {
    "low_engagement": "Very few likes for the views",
    "views_vs_audience": "Views far above the size of the audience",
    "view_burst": "Sudden surge of views without new likes",
    "live_spike": "Live viewers jump and fall back within minutes",
    "live_flatline": "Live viewer count hardly moves",
    "mechanical_steps": "Views grow in identical steps",
}
STATUSES = ("cleared", "watching", "confirmed")
METHOD = (
    "Each channel is compared with the other channels of the same group and with its own recent history. A flag is a pattern that is unusual, not proof of wrongdoing: "
    "public numbers cannot show who watched. Review the evidence, then mark the flag cleared, watching or confirmed."
)


def _question(*, days: int = 7, segment: str | None = None, language: str | None = None, channel_ids: list[int] | None = None, now: datetime | None = None, use_cache: bool = True) -> tuple:
    """What makes two scans the same question: the filters and the moment to the ten minutes (a briefing and the radar screen ask at slightly different instants)."""
    moment = utc(now) if now else now_utc()
    return (int(days), segment, language, tuple(sorted(channel_ids or [])), moment.replace(minute=moment.minute // 10 * 10, second=0, microsecond=0))


def _series(rows: list[Observation]) -> list[tuple[datetime, Observation]]:
    return [(utc(o.observed_at), o) for o in rows]


def _flag(code: str, severity: str, detail: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "title": SIGNALS[code], "severity": severity, "detail": detail, "evidence": evidence}


@ttl_cache(scale=10, stale=True, key=_question)   # about 7 minutes fresh, then handed out stale while it is worked out again
def scan(session: Session, *, days: int = 7, segment: str | None = None, language: str | None = None, channel_ids: list[int] | None = None, now: datetime | None = None, use_cache: bool = True) -> dict[str, Any]:
    if not 1 <= int(days) <= 28:
        raise ValueError("days must be between 1 and 28")
    days = int(days)
    now = utc(now) if now else now_utc()
    channels, languages = pick_channels(session, segment=segment, language=language, channel_ids=channel_ids)
    ids = [c.id for c in channels]
    since = now - timedelta(days=days)
    videos = channel_videos(session, ids) if ids else []
    recent = [v for v in videos if (m := parse_published(v.published_at)) and m >= since]
    latest = latest_observations(session, [v.id for v in recent])
    by_channel: dict[int, list[Video]] = defaultdict(list)
    for v in recent:
        by_channel[v.channel_id].append(v)

    # --- channel level: likes per view and views per subscriber against the comparable channels
    like_rate: dict[int, float] = {}
    pull: dict[int, float] = {}
    measured: dict[int, int] = {}
    from api.market_tools import _subscribers  # same latest-subscribers lookup the creator score uses
    subs = _subscribers(session, ids, since - timedelta(days=60))
    for c in channels:
        likes = views = 0
        n = 0
        vlist = []
        for v in by_channel.get(c.id, []):
            o = latest.get(v.id)
            if o is None or not o.view_count or o.view_count < 1000:
                continue
            n += 1
            views += int(o.view_count)
            likes += int(o.like_count or 0)
            vlist.append(int(o.view_count))
        measured[c.id] = n
        if n >= 5 and views:
            like_rate[c.id] = likes / views
            last = (subs.get(c.id) or {}).get("last")
            if last and last[1]:
                pull[c.id] = mean(vlist) / last[1]

    flags: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for c in channels:
        group = [k for k in like_rate if k != c.id and (next(x for x in channels if x.id == k).segment or "news") == (c.segment or "news")]
        peers = [like_rate[k] for k in group]
        if c.id in like_rate and len(peers) >= 4:
            z = robust_z(like_rate[c.id], peers)
            med = median(peers)
            if z is not None and z <= -3 and like_rate[c.id] < 0.4 * med:
                flags[c.id].append(_flag("low_engagement", "review", f"{like_rate[c.id] * 100:.2f}% likes per view against {med * 100:.2f}% for comparable channels.",
                                         {"like_percent": rnd(like_rate[c.id] * 100, 2), "peer_median_percent": rnd(med * 100, 2), "videos": measured[c.id], "z": rnd(z, 1)}))
        pgroup = [pull[k] for k in pull if k != c.id and (next(x for x in channels if x.id == k).segment or "news") == (c.segment or "news")]
        if c.id in pull and len(pgroup) >= 4:
            z = robust_z(pull[c.id], pgroup)
            med = median(pgroup)
            if z is not None and z >= 3.5 and pull[c.id] >= 3 * med:
                flags[c.id].append(_flag("views_vs_audience", "review", f"A recent video draws {pull[c.id] * 100:.0f}% of the subscriber count against {med * 100:.0f}% for comparable channels.",
                                         {"pull_percent": rnd(pull[c.id] * 100, 0), "peer_median_percent": rnd(med * 100, 0), "videos": measured[c.id], "z": rnd(z, 1)}))

    # --- video level: bursts and mechanical steps on each channel's most viewed recent videos
    top_ids: dict[int, list[Video]] = {}
    for c in channels:
        vs = [v for v in by_channel.get(c.id, []) if latest.get(v.id) and latest[v.id].view_count]
        vs.sort(key=lambda v: latest[v.id].view_count, reverse=True)
        top_ids[c.id] = vs[:4]
    vid_to_channel = {v.id: c for c, vs in ((c, top_ids[c.id]) for c in channels) for v in vs}
    if vid_to_channel:
        obs_rows = session.execute(select(Observation.video_id, Observation.channel_id, Observation.observed_at, Observation.view_count, Observation.like_count, Observation.comment_count, Observation.concurrent_viewers).where(Observation.video_id.in_(list(vid_to_channel)), Observation.observed_at >= since, Observation.view_count.is_not(None))
                                   .order_by(Observation.video_id, Observation.observed_at)).all()   # plain rows: building a full object for each of 100,000 samples was most of the time
        grouped: dict[int, list[Observation]] = defaultdict(list)
        for o in obs_rows:
            grouped[o.video_id].append(o)
        for vid, rows in grouped.items():
            c = vid_to_channel[vid]
            title = next((v.title for v in top_ids[c.id] if v.id == vid), "")
            _burst_and_steps(flags[c.id], rows, title)

    # --- live level: spikes and flat lines on streams of the last 24 hours
    if ids:
        live_rows = session.execute(select(Observation.video_id, Observation.channel_id, Observation.observed_at, Observation.view_count, Observation.like_count, Observation.comment_count, Observation.concurrent_viewers).where(Observation.channel_id.in_(ids), Observation.is_live.is_(True), Observation.concurrent_viewers.is_not(None),
                                                              Observation.observed_at >= now - timedelta(hours=24)).order_by(Observation.video_id, Observation.observed_at)).all()
        live_group: dict[int, list[Observation]] = defaultdict(list)
        for o in live_rows:
            live_group[o.video_id].append(o)
        for vid, rows in live_group.items():
            _live_signals(flags[rows[0].channel_id], rows)

    reviews = {(r.channel_id, r.signal): r for r in session.query(AuthenticityReview).filter(AuthenticityReview.channel_id.in_(ids)).all()} if ids else {}
    out = []
    counts = {"high": 0, "review": 0, "low": 0}
    for c in channels:
        merged: dict[str, dict[str, Any]] = {}
        for f in flags.get(c.id, []):
            cur = merged.get(f["code"])
            if cur is None:
                merged[f["code"]] = {**f, "occurrences": 1}
            else:
                cur["occurrences"] += 1
                if f["severity"] == "high":
                    cur["severity"] = "high"
        signals = []
        for code, f in merged.items():
            r = reviews.get((c.id, code))
            f["review"] = {"status": r.status, "note": r.note, "by": r.reviewed_by, "at": r.reviewed_at.isoformat()} if r else None
            if f["occurrences"] >= 2 and f["code"] in ("view_burst", "live_spike"):
                f["severity"] = "high"
            signals.append(f)
        open_signals = [s for s in signals if not s["review"] or s["review"]["status"] != "cleared"]
        risk = "high" if any(s["severity"] == "high" for s in open_signals) or len(open_signals) >= 3 else "review" if open_signals else "low"
        counts[risk] += 1
        out.append({"channel_id": c.id, "name": c.name, "segment": c.segment or "news", "language": languages[c.id], "risk": risk, "signals": signals, "videos_checked": measured.get(c.id, 0)})
    order = {"high": 0, "review": 1, "low": 2}
    out.sort(key=lambda r: (order[r["risk"]], -len(r["signals"]), r["name"].lower()))
    result = {"days": days, "filters": {"segment": segment, "language": language}, "method": METHOD, "summary": counts, "channels": out, "signals": SIGNALS, "generated_at": now.isoformat()}
    return result


def _burst_and_steps(sink: list[dict[str, Any]], rows: list[Observation], title: str) -> None:
    if len(rows) < 8:
        return
    total_views = rows[-1].view_count or 0
    total_likes = (rows[-1].like_count or 0)
    like_per_view = total_likes / total_views if total_views else 0
    rates, intervals = [], []
    for a, b in zip(rows, rows[1:]):
        dt = (utc(b.observed_at) - utc(a.observed_at)).total_seconds() / 3600
        if dt < 5 / 60:
            continue
        dv = (b.view_count or 0) - (a.view_count or 0)
        dl = (b.like_count or 0) - (a.like_count or 0)
        intervals.append((a, b, dv, dl, dt))
        rates.append(dv / dt)
    if len(rates) >= 6:
        for i, (a, b, dv, dl, dt) in enumerate(intervals):
            base = median([r for k, r in enumerate(rates) if k != i]) or 0
            if dv >= max(5000, 0.03 * total_views) and dv / dt >= max(8 * base, 5000) and (dl <= 0 or dl / dv < 0.2 * like_per_view):
                sink.append(_flag("view_burst", "review", f"{dv:,} views arrived in {dt * 60:.0f} minutes ({dv / dt:,.0f} an hour against a usual {base:,.0f}) with {max(dl, 0):,} new likes.",
                                  {"video": title[:90], "from": utc(a.observed_at).isoformat(), "views_added": dv, "minutes": round(dt * 60), "usual_views_per_hour": round(base), "new_likes": max(dl, 0)}))
                break
    deltas = [(b.view_count or 0) - (a.view_count or 0) for a, b in zip(rows, rows[1:])]
    run = best = 1
    for x, y in zip(deltas, deltas[1:]):
        run = run + 1 if x == y and x >= 100 else 1
        best = max(best, run)
    if best >= 6:
        step = next(x for x, y in zip(deltas, deltas[1:]) if x == y and x >= 100)
        sink.append(_flag("mechanical_steps", "review", f"Views grew by exactly {step:,} for {best + 1} samples in a row.", {"video": title[:90], "step": step, "samples_in_a_row": best + 1}))


def _live_signals(sink: list[dict[str, Any]], rows: list[Observation]) -> None:
    values = [int(o.concurrent_viewers or 0) for o in rows]
    times = [utc(o.observed_at) for o in rows]
    if len(values) >= 60 and mean(values) and mean(values) >= 1000:
        sd = stdev(values) or 0
        cv = sd / mean(values)
        if cv < 0.004:
            sink.append(_flag("live_flatline", "review", f"{len(values)} samples over {(times[-1] - times[0]).total_seconds() / 3600:.1f} hours stayed within {cv * 100:.2f}% of {mean(values):,.0f} viewers.",
                              {"samples": len(values), "hours": round((times[-1] - times[0]).total_seconds() / 3600, 1), "average": round(mean(values)), "variation_percent": rnd(cv * 100, 2)}))
    for i in range(6, len(values)):
        base = median(values[max(0, i - 10):i])
        if base <= 0 or values[i] < 3 * base or values[i] - base < 2000:
            continue
        for j in range(i + 1, len(values)):
            if (times[j] - times[i]).total_seconds() > 900:
                break
            if values[j] <= 1.5 * base:
                sink.append(_flag("live_spike", "review", f"Viewers jumped from about {base:,.0f} to {values[i]:,} and were back near {values[j]:,} within {(times[j] - times[i]).total_seconds() / 60:.0f} minutes.",
                                  {"at": times[i].isoformat(), "before": round(base), "peak": values[i], "after": values[j], "minutes": round((times[j] - times[i]).total_seconds() / 60)}))
                return
        # a spike that is still up at the end of the data is not judged yet


def risk_by_channel(session: Session, **kwargs: Any) -> dict[int, dict[str, Any]]:
    result = scan(session, **kwargs)
    return {r["channel_id"]: {"risk": r["risk"], "signals": [s["code"] for s in r["signals"] if not s["review"] or s["review"]["status"] != "cleared"]} for r in result["channels"]}


def set_review(session: Session, *, channel_id: int, signal: str, status: str, note: str, by: str) -> dict[str, Any]:
    if signal not in SIGNALS:
        raise ValueError("unknown signal")
    if status not in STATUSES:
        raise ValueError("status must be cleared, watching or confirmed")
    if len(note or "") > 2000:
        raise ValueError("note is too long")
    row = session.query(AuthenticityReview).filter_by(channel_id=channel_id, signal=signal).one_or_none()
    if row is None:
        row = AuthenticityReview(channel_id=channel_id, signal=signal, status=status, note=(note or "").strip() or None, reviewed_by=by)
        session.add(row)
    else:
        row.status, row.note, row.reviewed_by, row.reviewed_at = status, (note or "").strip() or None, by, datetime.now(UTC)
    session.commit()
    scan.cache_clear()   # a decision changes what the radar shows
    return {"channel_id": channel_id, "signal": signal, "status": status, "note": row.note, "by": by}
