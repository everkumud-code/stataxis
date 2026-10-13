"""How complete is the live record of each channel on each day?

For every live stream and every Indian-time day, the collector should have one reading each poll interval from the stream's first reading of the day to its last. Completeness is the readings that are there
divided by the readings that should be there (never more than 100%). A day with gaps (the collector was down, a quota pause, a stream the collector found late) shows below 100%.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.ttl_cache import ttl_cache
from collector.storage import Channel, Observation

IST = timedelta(hours=5, minutes=30)


def poll_seconds() -> int:
    try:
        return max(5, int(float(os.getenv("LIVE_POLL_SECONDS", "30") or 30)))
    except ValueError:
        return 30


def _ist_day(session: Session):
    if session.get_bind().dialect.name == "postgresql":
        return func.date(func.timezone("Asia/Kolkata", Observation.observed_at))
    return func.date(Observation.observed_at, "+330 minutes")


@ttl_cache(stale=True)
def channel_day_completeness(session: Session, *, days: int = 3, now: datetime | None = None) -> dict[str, Any]:
    days = max(1, min(int(days), 14))
    now = now or datetime.now(UTC)
    local_today = (now + IST).date()
    since = datetime.combine(local_today - timedelta(days=days - 1), datetime.min.time(), tzinfo=UTC) - IST
    day = _ist_day(session).label("day")
    rows = session.execute(select(Observation.channel_id, Observation.video_id, day, func.count().label("n"), func.min(Observation.observed_at).label("t0"), func.max(Observation.observed_at).label("t1"))
                           .where(Observation.is_live.is_(True), Observation.concurrent_viewers.is_not(None), Observation.observed_at >= since)
                           .group_by(Observation.channel_id, Observation.video_id, day)).all()
    step = poll_seconds()
    cells: dict[tuple[int, str], dict[str, float]] = {}
    for channel_id, _video_id, d, n, t0, t1 in rows:
        span = max(0.0, (t1 - t0).total_seconds())
        expected = int(span // step) + 1
        c = cells.setdefault((channel_id, str(d)), {"streams": 0, "readings": 0, "expected": 0, "have": 0, "hours": 0.0})
        c["streams"] += 1
        c["readings"] += int(n)
        c["expected"] += expected
        c["have"] += min(int(n), expected)
        c["hours"] += span / 3600
    names = {cid: name for cid, name in session.execute(select(Channel.id, Channel.name).where(Channel.active.is_(True))).all()}
    out = [{"channel_id": cid, "channel": names[cid], "day": d, "streams": int(c["streams"]), "readings": int(c["readings"]), "expected": int(c["expected"]),
            "hours_live": round(c["hours"], 1), "completeness_percent": round(100.0 * c["have"] / c["expected"], 1) if c["expected"] else None}
           for (cid, d), c in cells.items() if cid in names]
    out.sort(key=lambda r: (r["day"], r["channel"].lower()), reverse=False)
    by_day: dict[str, list[float]] = {}
    for r in out:
        if r["completeness_percent"] is not None:
            by_day.setdefault(r["day"], []).append(r["completeness_percent"])
    return {"poll_seconds": step, "days": days, "rows": out,
            "by_day": [{"day": d, "channels": len(v), "average_percent": round(sum(v) / len(v), 1), "lowest_percent": min(v)} for d, v in sorted(by_day.items(), reverse=True)],
            "method": f"For each live stream and each Indian-time day: readings present divided by the readings expected (one every {step} seconds from the stream's first reading of the day to its last), capped at 100%. "
                      "A channel's figure for the day adds its streams together. It measures gaps in StatAxis's own record; it does not say how long a channel was live."}
