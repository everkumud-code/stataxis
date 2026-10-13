"""Prime-time forecasts, written down before the slot and scored afterwards.

The method is deliberately plain so anyone can check it: a channel's average live audience in the 19:00-22:00 slot (Indian time) is expected to be the median of that slot's averages on up to the
7 days before. It is written down at 06:00 IST on the day; once the slot is over, the real average is measured and the forecast is scored. A forecast counts as a hit when it is within 20% of what happened.
The track record (hit rate and typical error) is public to every person who can open this screen, and it is computed from the stored forecasts, not from a summary written by hand.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from api.live_stats import live_window_stats
from api.market_common import IST, ist_hours
from collector.storage import Channel, Prediction

SLOT = (19, 22)
SLOT_LABEL = f"{SLOT[0]:02d}:00-{SLOT[1]:02d}:00"
HISTORY_DAYS = 7
HIT_WITHIN_PERCENT = 20.0
METHOD = (f"Expected average live viewers (all feeds) in {SLOT_LABEL} IST = the median of that slot's daily averages over up to the {HISTORY_DAYS} days before, written down at 06:00 IST the same day. "
          f"After the slot, the measured average is compared: a hit is within {HIT_WITHIN_PERCENT:g}%. Channels with no earlier day in the slot get no forecast.")


def _day_averages(session: Session, day: date) -> dict[int, float]:
    start, end = ist_hours(day, *SLOT)
    stats = live_window_stats(session, start_at=start, end_at=end, bucket_seconds=60)
    return {row["channel_id"]: float(row["feeds"]["all"]["average"]) for row in stats["channels"] if row["feeds"]["all"]["average"] is not None}


def make_predictions(session: Session, target_day: date, *, now: datetime | None = None) -> int:
    """Write the forecasts for ``target_day``'s slot (once; existing ones are never changed). Returns how many were written."""
    now = now or datetime.now(UTC)
    start_of_slot, _ = ist_hours(target_day, *SLOT)
    if now >= start_of_slot:
        return 0   # a forecast written after the slot has started is not a forecast
    existing = {cid for (cid,) in session.query(Prediction.channel_id).filter(Prediction.target_date == target_day.isoformat(), Prediction.slot == SLOT_LABEL)}
    history: dict[int, list[float]] = {}
    for back in range(1, HISTORY_DAYS + 1):
        day = target_day - timedelta(days=back)
        if ist_hours(day, *SLOT)[1] > now:
            continue
        for channel_id, average in _day_averages(session, day).items():
            history.setdefault(channel_id, []).append(average)
    active = {cid for (cid,) in session.query(Channel.id).filter(Channel.active.is_(True))}
    written = 0
    for channel_id, values in history.items():
        if channel_id in existing or channel_id not in active or not values:
            continue
        session.add(Prediction(made_at=now, target_date=target_day.isoformat(), slot=SLOT_LABEL, channel_id=channel_id, predicted=round(median(values), 1), days_used=len(values)))
        written += 1
    session.commit()
    return written


def score_predictions(session: Session, *, now: datetime | None = None) -> int:
    """Measure the slots that are over and score every forecast written for them. Returns how many were scored."""
    now = now or datetime.now(UTC)
    pending = session.query(Prediction).filter(Prediction.scored_at.is_(None)).all()
    by_day: dict[str, list[Prediction]] = {}
    for row in pending:
        if ist_hours(date.fromisoformat(row.target_date), *SLOT)[1] <= now:
            by_day.setdefault(row.target_date, []).append(row)
    scored = 0
    for day_text, rows in by_day.items():
        actuals = _day_averages(session, date.fromisoformat(day_text))
        for row in rows:
            actual = actuals.get(row.channel_id)
            row.scored_at = now
            if actual is None or row.predicted <= 0:
                continue   # not live in the slot: nothing to compare, and it is not counted either way
            row.actual = round(actual, 1)
            row.error_percent = round(100.0 * (actual - row.predicted) / row.predicted, 1)
            row.hit = abs(row.error_percent) <= HIT_WITHIN_PERCENT
            scored += 1
    session.commit()
    return scored


def track_record(session: Session, *, days: int = 30) -> dict[str, Any]:
    since = (datetime.now(IST).date() - timedelta(days=days)).isoformat()
    rows = session.query(Prediction).filter(Prediction.actual.is_not(None), Prediction.target_date >= since).all()
    errors = sorted(abs(r.error_percent) for r in rows if r.error_percent is not None)
    per_day: dict[str, list[Prediction]] = {}
    for r in rows:
        per_day.setdefault(r.target_date, []).append(r)
    return {"scored": len(rows), "hits": sum(1 for r in rows if r.hit), "hit_rate_percent": round(100.0 * sum(1 for r in rows if r.hit) / len(rows), 1) if rows else None,
            "median_error_percent": round(errors[len(errors) // 2], 1) if errors else None,
            "by_day": [{"date": d, "scored": len(v), "hit_rate_percent": round(100.0 * sum(1 for r in v if r.hit) / len(v), 1)} for d, v in sorted(per_day.items(), reverse=True)][:14]}


def forecast_overview(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    names = {cid: name for cid, name in session.query(Channel.id, Channel.name).filter(Channel.active.is_(True))}   # a channel switched off after its forecast was written is not listed
    today = (now or datetime.now(UTC)).astimezone(IST).date()
    def line(r: Prediction) -> dict[str, Any]:
        return {"channel_id": r.channel_id, "channel": names.get(r.channel_id, "?"), "date": r.target_date, "slot": r.slot, "predicted": round(r.predicted), "days_used": r.days_used,
                "actual": None if r.actual is None else round(r.actual), "error_percent": r.error_percent, "hit": r.hit, "made_at": r.made_at.isoformat()}
    upcoming = session.query(Prediction).filter(Prediction.target_date >= today.isoformat(), Prediction.scored_at.is_(None), Prediction.channel_id.in_(list(names))).order_by(Prediction.predicted.desc()).limit(25).all()
    recent = session.query(Prediction).filter(Prediction.actual.is_not(None), Prediction.channel_id.in_(list(names))).order_by(Prediction.target_date.desc(), Prediction.predicted.desc()).limit(40).all()
    total = int(session.query(func.count(Prediction.id)).scalar() or 0)
    return {"method": METHOD, "slot": SLOT_LABEL, "total_written": total, "track_record": track_record(session), "upcoming": [line(r) for r in upcoming], "recent": [line(r) for r in recent]}
