"""The public status of the measurement: is it running, how fresh is it, and how much of the time has it been running.

Uptime here is measurement availability: the share of five-minute periods, over the window, in which at least one new reading was stored. It is worked out from the stored readings themselves, so it is
what the data says, and it covers only the time since StatAxis began recording (it never claims more history than exists).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import cast, func, select, Integer
from sqlalchemy.orm import Session

from collector.storage import Channel, CollectionRun, Observation

SLOT_SECONDS = 300


def _slot(session: Session):
    if session.get_bind().dialect.name == "postgresql":
        return func.floor(func.extract("epoch", Observation.observed_at) / SLOT_SECONDS)
    epoch = cast(func.strftime("%s", Observation.observed_at), Integer)
    return epoch - (epoch % SLOT_SECONDS)   # the start of the five-minute period, as a whole number


def availability(session: Session, hours: float, *, now: datetime | None = None) -> dict[str, Any]:
    """Share of five-minute periods in the last ``hours`` hours (or since the first reading, if that is later) with at least one reading."""
    now = now or datetime.now(UTC)
    first = session.execute(select(func.min(Observation.observed_at))).scalar()
    if first is None:
        return {"hours": hours, "percent": None, "covers_hours": 0.0}
    first = first if first.tzinfo else first.replace(tzinfo=UTC)
    start = max(now - timedelta(hours=hours), first)
    periods = max(1, int((now - start).total_seconds() // SLOT_SECONDS))
    present = int(session.execute(select(func.count(func.distinct(_slot(session)))).where(Observation.observed_at >= start, Observation.observed_at <= now)).scalar() or 0)
    return {"hours": hours, "percent": round(min(100.0, 100.0 * present / periods), 2), "covers_hours": round((now - start).total_seconds() / 3600, 1)}


def status_snapshot(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    last = session.execute(select(func.max(Observation.observed_at))).scalar()
    age = (now - (last if last.tzinfo else last.replace(tzinfo=UTC))).total_seconds() / 60 if last else None
    run = session.execute(select(CollectionRun).where(CollectionRun.status != "running").order_by(CollectionRun.started_at.desc()).limit(1)).scalar_one_or_none()   # a pass in progress is not a verdict: the last one that ended is
    run_age = None
    if run is not None:
        reference = run.finished_at or run.started_at
        run_age = (now - (reference if reference.tzinfo else reference.replace(tzinfo=UTC))).total_seconds() / 60
    measuring = "operational" if age is not None and age < 5 else "delayed" if age is not None and age < 30 else "down"
    collecting = "operational" if run is not None and run.status in ("success", "partial") and run_age is not None and run_age < 360 else "delayed"
    overall = "operational" if measuring == "operational" and collecting == "operational" else "degraded" if measuring != "down" else "down"
    live = session.execute(select(func.count(func.distinct(Observation.channel_id))).where(Observation.is_live.is_(True), Observation.observed_at >= now - timedelta(seconds=180))).scalar() or 0
    return {"status": overall, "components": [
                {"name": "Live measurement", "status": measuring, "detail": "last reading " + (f"{age:.0f} minutes ago" if age is not None else "none yet")},
                {"name": "Collection of uploads and channel statistics", "status": collecting, "detail": (f"last pass {run.status}, {run_age:.0f} minutes ago" if run is not None else "none yet")}],
            "channels_measured": session.query(Channel).filter(Channel.active.is_(True)).count(), "channels_live_now": int(live), "readings_stored": int(session.execute(select(func.max(Observation.id))).scalar() or 0),
            "measurement_availability": [availability(session, 24, now=now), availability(session, 24 * 7, now=now), availability(session, 24 * 30, now=now)],
            "uptime_note": "Measurement availability: the share of five-minute periods with at least one new reading, since StatAxis began recording. It is worked out from the stored readings.", "generated_at": now.isoformat()}
