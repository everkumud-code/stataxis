"""What a periodic report says: the content that the one-pager and the booklet (api/report_layouts.py) are drawn from, for a real period or as an illustrative sample.

Periods are calendar periods that end the day before the report is sent (Indian time):

  daily          yesterday                                   sent every day
  weekly         Monday to Sunday of last week               sent on Mondays
  fortnightly    the 1st-14th or the 16th-end of the month   sent on the 15th and the 1st
  monthly        last calendar month                         sent on the 1st
  quarterly      last calendar quarter                       sent on 1 Jan, 1 Apr, 1 Jul, 1 Oct
  half-yearly    Apr-Sep or Oct-Mar (the financial year's halves)   sent on 1 Apr and 1 Oct
  yearly         the financial year Apr-Mar that just ended  sent on 1 April

A report is only made when StatAxis has measured at least 60% of the period; until then the subscription is told it is waiting for history (NotEnoughHistory), never sent half-empty.
The ranking is by views gained by the videos uploaded in the period (as in the Weekly report), the STX Index beside each channel is its current score, and every sentence is worked out from the figures.
"""

from __future__ import annotations

import calendar
import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from api.market_common import IST, MAX_RANGE_DAYS, rnd
from api.market_tools import weekly_views
from api.stx_attach import stx_map
from collector.storage import Observation

INTERVALS = {
    "daily": {"label": "Daily report", "unit": "day"}, "weekly": {"label": "Weekly report", "unit": "week"}, "fortnightly": {"label": "Fortnightly report", "unit": "fortnight"},
    "monthly": {"label": "Monthly report", "unit": "month"}, "quarterly": {"label": "Quarterly report", "unit": "quarter"},
    "half-yearly": {"label": "Half-yearly report", "unit": "half-year"}, "yearly": {"label": "Yearly report", "unit": "year"},
}
MIN_COVERAGE = 0.6


class NotEnoughHistory(Exception):
    """StatAxis has not measured enough of the period yet."""


def _last_of_month(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _prev_month(d: date) -> tuple[int, int]:
    return (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)


def period_for(interval: str, d: date) -> tuple[date, date] | None:
    """The period to report when sending on day ``d`` (an Indian date), or None when ``d`` is not a send day for this interval."""
    if interval == "daily":
        return d - timedelta(days=1), d - timedelta(days=1)
    if interval == "weekly":
        return (d - timedelta(days=7), d - timedelta(days=1)) if d.weekday() == 0 else None
    if interval == "fortnightly":
        if d.day == 15:
            return date(d.year, d.month, 1), date(d.year, d.month, 14)
        if d.day == 1:
            y, m = _prev_month(d)
            return date(y, m, 16), _last_of_month(y, m)
        return None
    if d.day != 1:
        return None
    y, m = _prev_month(d)
    if interval == "monthly":
        return date(y, m, 1), _last_of_month(y, m)
    if interval == "quarterly" and d.month in (1, 4, 7, 10):
        start_month = d.month - 3 if d.month > 3 else 10
        return date(d.year if d.month > 3 else d.year - 1, start_month, 1), _last_of_month(y, m)
    if interval == "half-yearly" and d.month in (4, 10):
        return (date(d.year - 1, 10, 1) if d.month == 4 else date(d.year, 4, 1)), _last_of_month(y, m)
    if interval == "yearly" and d.month == 4:
        return date(d.year - 1, 4, 1), date(d.year, 3, 31)
    return None


def _fy(d: date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"FY {start}-{str(start + 1)[2:]}"


def period_label(interval: str, start: date, end: date) -> str:
    def day(x: date) -> str:
        return f"{x.day} {x:%b %Y}"
    if interval == "daily":
        return day(start)
    if interval in ("weekly", "fortnightly"):
        return f"{start.day} – {day(end)}" if start.month == end.month and start.year == end.year else f"{start.day} {start:%b} – {day(end)}"
    if interval == "monthly":
        return f"{start:%B %Y}"
    if interval == "quarterly":
        return f"{start:%b} – {end:%b %Y} (Q{((start.month - 4) % 12) // 3 + 1}, {_fy(start)})"
    if interval == "half-yearly":
        return f"{start:%b %Y} – {end:%b %Y} (H{1 if start.month == 4 else 2}, {_fy(start)})"
    return f"{_fy(start)} ({start:%b %Y} – {end:%b %Y})"


# ------------------------------------------------------------------------------------------------ the words
def compose(interval: str, group: str, period: str, rows: list[dict[str, Any]], points: list[tuple[str, float]], trend: tuple[str, str], *, third_kpi: dict[str, str],
            mover: dict[str, Any] | None = None, days: int, sample: bool = False, notes: list[str] | None = None) -> dict[str, Any]:
    """The content dictionary from ranked rows ({name, views in millions, stx or None}); every sentence comes from these figures."""
    spec = INTERVALS[interval]
    unit = spec["unit"]
    rows = sorted((dict(r) for r in rows), key=lambda r: r["views"], reverse=True)
    total = sum(r["views"] for r in rows) or 1.0
    for i, r in enumerate(rows, start=1):
        r["rank"], r["share"] = i, round(100 * r["views"] / total, 1)
    scored = [r for r in rows if r.get("stx") is not None]
    best = max(scored, key=lambda r: r["stx"]) if scored else None
    stx = {"leader": best["name"], "leader_score": best["stx"], "average": round(sum(r["stx"] for r in scored) / len(scored), 1), "scored": len(scored), "of": len(rows)} if best else None
    top, second = rows[0], rows[1] if len(rows) > 1 else rows[0]
    top3 = round(sum(r["share"] for r in rows[:3]), 1)
    gap = top["views"] - second["views"]
    highlights = ([f"{best['name']} has the highest STX Index: {best['stx']:.1f}."] if best else []) + [f"{top['name']} leads on views with {top['views']:,.1f}M ({top['share']}% of the total)."]
    if mover:
        highlights.append(f"{mover['name']} moved up {mover['places']} place{'s' if mover['places'] > 1 else ''} against the previous {unit}.")
    if len(rows) >= 3:
        highlights.append(f"The top three channels hold {top3}% of all views.")
    findings = [{"headline": (f"{top['name']} leads on views, {best['name']} leads on STX" if best and top["name"] != best["name"] else f"{top['name']} leads on both views and STX") if best else f"{top['name']} leads on views",
                 "detail": f"{top['name']} collected {top['views']:,.1f}M views" + (f", {top['views'] / second['views']:.2f} times {second['name']}" if second is not top and second["views"] else "") + "."
                           + (f" The STX Index, which also weighs audience, momentum and consistency, is highest for {best['name']} at {best['stx']:.1f}." if best else ""),
                 "so_what": "Views show who was watched; STX shows who is strongest overall. Read the two together before choosing where to place a campaign."}]
    if len(rows) >= 3:
        findings.append({"headline": f"The top three hold {top3}% of all views", "detail": f"{top['name']}, {second['name']} and {rows[2]['name']} together hold {top3}% of the {total:,.1f}M views; the other {len(rows) - 3} share the rest.",
                         "so_what": "A crowded top means rankings can change with one big story; a wide gap means the lead is safer."})
    if mover:
        findings.append({"headline": f"{mover['name']} is the mover of the {unit}", "detail": f"{mover['name']} now stands at number {mover['rank']}" + (f" with an STX Index of {mover['stx']:.1f}" if mover.get("stx") is not None else "") + f", up on the previous {unit}.",
                         "so_what": "A channel that climbs on STX before it climbs on views is often the one to watch next."})
    if second is not top and second["views"]:
        findings.append({"headline": f"The gap between {top['name']} and {second['name']} is {gap:,.1f}M views", "detail": f"That is {100 * gap / second['views']:.1f}% more than the runner-up."
                         + (f" The channels at the bottom, {rows[-2]['name']} and {rows[-1]['name']}, hold {rows[-2]['share'] + rows[-1]['share']:.1f}% between them." if len(rows) >= 4 else ""),
                         "so_what": "A wide gap at the top is a safer lead; a narrow one can change in a single news cycle."})
    if len(scored) >= 2:
        low, high = min(r["stx"] for r in scored), max(r["stx"] for r in scored)
        findings.append({"headline": f"STX is spread from {low:.1f} to {high:.1f}", "detail": f"The average STX Index of the {len(scored)} scored channels is {stx['average']:.1f}. {best['name']} is {best['stx'] - stx['average']:.1f} points above the average.",
                         "so_what": "STX separates channels that look alike on views: use it to choose between two channels that draw similar audiences."})
    observations = [f"Views are measured on YouTube for the videos uploaded in this {unit}, as last measured; STX is each channel's current score.",
                    f"This {unit} covers {days} day{'s' if days != 1 else ''}; a short window can be moved by a single event.",
                    "Channels with little data carry a lower confidence and are pulled toward 50 so they cannot look more certain than they are.",
                    "The ranking is by views; the STX column beside it ranks the same channels by overall strength, so the two orders can differ."] + (notes or [])
    viewpoint = ((f"STX Index: {best['name']} is highest at {best['stx']:.1f}; the average of the {len(scored)} scored channels is {stx['average']:.1f}. " if best else "")
                 + f"{top['name']}" + (f" and {second['name']} lead on views" if second is not top else " leads on views") + f", and the audience is {'spread widely' if top['share'] < 30 else 'concentrated in a few channels'}. "
                 "Read the figures with the period in mind: they are measured on YouTube, not on television.")
    return {"interval": interval, "title": f"{group} · {spec['label']}", "period": period, "kicker": spec["label"].upper(), "sample": sample, "stx": stx,
            "kpis": [{"label": "Total views", "value": f"{total:,.1f}M", "detail": "videos uploaded in the period"}, {"label": "Highest STX Index", "value": f"{best['stx']:.1f}" if best else "-", "detail": best["name"] if best else "not enough data yet"}, third_kpi,
                     {"label": "Channels measured", "value": str(len(rows)), "detail": f"{len(scored)} with an STX Index"}],
            "ranking": rows, "trend": {"title": trend[0], "unit": trend[1], "points": points}, "highlights": highlights, "findings": findings, "observations": observations, "viewpoint": viewpoint}


# ------------------------------------------------------------------------------------------------ real content
def _gather(session: Session, start: date, end: date, language: str | None, segment: str | None) -> tuple[dict[int, dict[str, Any]], str]:
    """Views and videos by channel for the videos uploaded between two Indian dates, in pieces of at most 31 days; and the name of the largest group."""
    acc: dict[int, dict[str, Any]] = {}
    d = start
    while d <= end:
        e = min(end, d + timedelta(days=MAX_RANGE_DAYS - 1))
        for g in weekly_views(session, start_date=d.isoformat(), end_date=e.isoformat(), language=language, segment=segment)["groups"]:
            for ch in g["channels"]:
                a = acc.setdefault(ch["channel_id"], {"name": ch["name"], "views": 0, "videos": 0, "label": g["label"]})
                a["views"] += ch["views"]
                a["videos"] += ch["videos"]
        d = e + timedelta(days=1)
    totals: dict[str, int] = {}
    for a in acc.values():
        totals[a["label"]] = totals.get(a["label"], 0) + a["views"]
    label = max(totals, key=lambda k: totals[k]) if totals else ""
    return {cid: a for cid, a in acc.items() if a["label"] == label}, label


def _parts(interval: str, start: date, end: date) -> list[tuple[str, date, date]]:
    """The sub-periods of the trend chart: days, weeks or calendar months."""
    out: list[tuple[str, date, date]] = []
    if interval in ("weekly", "fortnightly"):
        d = start
        while d <= end:
            out.append((f"{d.day} {d:%b}" if not out else str(d.day), d, d))
            d += timedelta(days=1)
    elif interval == "monthly":
        d, n = start, 1
        while d <= end:
            e = min(end, d + timedelta(days=6))
            out.append((f"Week {n}", d, e))
            d, n = e + timedelta(days=1), n + 1
    else:
        y, m = start.year, start.month
        while date(y, m, 1) <= end:
            out.append((f"{calendar.month_abbr[m]}", max(start, date(y, m, 1)), min(end, _last_of_month(y, m))))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def data_since(session: Session) -> date | None:
    first = session.query(func.min(Observation.observed_at)).scalar()
    if first is None:
        return None
    first = first if first.tzinfo else first.replace(tzinfo=UTC)
    return first.astimezone(IST).date()


def build_content(session: Session, interval: str, start: date, end: date, *, language: str | None = None, segment: str | None = None) -> dict[str, Any]:
    """The real report for one period. Raises NotEnoughHistory when StatAxis has measured too little of it."""
    days = (end - start).days + 1
    since = data_since(session)
    if since is None or end < since:
        raise NotEnoughHistory("StatAxis has no measurements for this period yet")
    covered = (end - max(start, since)).days + 1
    if covered < max(1, math.ceil(MIN_COVERAGE * days)):
        raise NotEnoughHistory(f"StatAxis has measured {covered} of the {days} days of this period; the report is sent when at least {int(MIN_COVERAGE * 100)}% is covered")
    start_eff = max(start, since)
    acc, group = _gather(session, start_eff, end, language, segment)
    if not acc:
        raise NotEnoughHistory("no video was measured in this period with these filters")
    stx = stx_map(session)
    rows = [{"channel_id": cid, "name": a["name"], "views": a["views"] / 1e6, "stx": (stx.get(cid) or {}).get("score")} for cid, a in acc.items() if a["views"] > 0]
    if not rows:
        raise NotEnoughHistory("no views were measured in this period with these filters")
    mover = None
    prev_end = start_eff - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    if since <= prev_start:
        prev, _ = _gather(session, prev_start, prev_end, language, segment)
        prev_order = {cid: i for i, cid in enumerate(sorted(prev, key=lambda c: prev[c]["views"], reverse=True), start=1)}
        now_order = {r["channel_id"]: i for i, r in enumerate(sorted(rows, key=lambda r: r["views"], reverse=True), start=1)}
        gains = [(prev_order[cid] - now_order[cid], cid) for cid in now_order if cid in prev_order and prev_order[cid] > now_order[cid]]
        if gains:
            places, cid = max(gains)
            r = next(x for x in rows if x["channel_id"] == cid)
            mover = {"name": r["name"], "places": places, "rank": now_order[cid], "stx": r.get("stx")}
    ids = {r["channel_id"] for r in rows}
    if interval == "daily":
        from api.live_stats import live_window_stats
        points: list[tuple[str, float]] = []
        for h in range(0, 24, 2):
            s0 = datetime(start.year, start.month, start.day, tzinfo=IST) + timedelta(hours=h)
            stats = live_window_stats(session, start_at=s0, end_at=s0 + timedelta(hours=2), bucket_seconds=60)
            points.append((f"{h:02d}h", float(sum((c["feeds"]["all"]["average"] or 0) for c in stats["channels"] if c["channel_id"] in ids))))
        trend = ("Audience through the day", "average concurrent viewers, all channels")
    else:
        points = []
        for label, a, b in _parts(interval, start_eff, end):
            sub, _ = _gather(session, a, b, language, segment)
            points.append((label, rnd(sum(v["views"] for cid, v in sub.items() if cid in ids) / 1e6, 1) or 0.0))
        trend = ("Views " + {"weekly": "day by day", "fortnightly": "day by day", "monthly": "week by week"}.get(interval, "month by month"), "million views of new videos")
    notes = [f"StatAxis has measured from {since:%d %b %Y}; this report covers {start_eff:%d %b} to {end:%d %b %Y}."] if start_eff > start else []
    content = compose(interval, group, period_label(interval, start, end), rows, points, trend, days=days, notes=notes,
                      third_kpi={"label": "New videos", "value": f"{sum(acc[r['channel_id']]['videos'] for r in rows):,}", "detail": "measured in the period"}, mover=mover)
    try:
        from api.social import report_block   # the social media part is optional: a report is still complete without it
        content["social"] = report_block(session, language=language, segment=segment, days=days)
    except Exception:   # noqa: BLE001
        content["social"] = None
    return content
