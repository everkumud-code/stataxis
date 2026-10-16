"""The collector's small scheduled jobs, run in their own thread beside the live poll and the collection pass:

  every minute   check people's alerts against the live audiences (api/alerts.py)
  every 10 min   send the report e-mails that are due (api/report_subscriptions.py); read the Facebook, Instagram and X accounts that are due (collector/social/service.py); close collection runs a restart cut short; write the day's note from 09:00 IST (and the week's on Monday); write the 19:00-22:00 forecasts from 06:00 IST until the slot
                 starts; score the forecasts of a slot once it is over
Each job has its own database session and its own error handling, so a failing job never stops the others or the collection.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
IST = timedelta(hours=5, minutes=30)
_SOCIAL_RETENTION_LAST = [-1e9]


def _guarded(engine: Any, name: str, job: Any) -> None:
    try:
        with Session(engine) as session:
            result = job(session)
        if result:
            logger.info("job %s counts done=%s", name, result)
    except Exception as exc:   # one job failing must not stop the others
        logger.warning("job %s failed: %s", name, type(exc).__name__)


def _remove_old_snapshots(session: Session, now: datetime) -> int:
    """Stored answers older than a day are never read again (a newer one replaced them, or the channel list changed since): drop them."""
    from collector.storage import Snapshot

    removed = session.query(Snapshot).filter(Snapshot.computed_at < now - timedelta(days=1)).delete(synchronize_session=False)
    session.commit()
    return removed


def _social_pass(session: Session, now: datetime) -> dict[str, Any]:
    """Read the Facebook, Instagram and X accounts that are due (40 at most each pass; the rest follow on the next passes)."""
    from collector.social.service import collect_social

    counts = collect_social(session, now=now, limit=40)
    if time.monotonic() - _SOCIAL_RETENTION_LAST[0] > 3600:   # the keeping rules (36 months of figures, 30 days of post text) are applied about once an hour
        _SOCIAL_RETENTION_LAST[0] = time.monotonic()
        from collector.social.retention import run_social_retention

        counts.update({f"retention_{k}": v for k, v in run_social_retention(session, now).items()})
    return {k: v for k, v in counts.items() if v}


def minute_jobs(engine: Any, now: datetime) -> None:
    from api.alerts import evaluate_alerts

    _guarded(engine, "alerts", lambda s: evaluate_alerts(s, now=now))


def periodic_jobs(engine: Any, now: datetime) -> None:
    from api.forecasts import make_predictions, score_predictions
    from api.notes import due_notes, generate_note
    from collector.run import close_interrupted_runs

    from api.report_subscriptions import send_due

    local = now + IST
    _guarded(engine, "close_interrupted_runs", close_interrupted_runs)
    _guarded(engine, "report_emails", lambda s: send_due(s, now=now))
    _guarded(engine, "social", lambda s: _social_pass(s, now))
    _guarded(engine, "old_snapshots_removed", lambda s: _remove_old_snapshots(s, now))
    for kind, day in due_notes(now):
        _guarded(engine, f"note_{kind}", lambda s, k=kind, d=day: int(generate_note(s, k, d, now=now)))
    if local.hour >= 6:
        _guarded(engine, "forecasts_written", lambda s: make_predictions(s, local.date(), now=now))
    _guarded(engine, "forecasts_scored", lambda s: score_predictions(s, now=now))


def run_jobs(engine: Any, stop: Event, *, minute: int = 60, periodic: int = 600) -> None:
    next_minute = time.monotonic() + 45
    next_periodic = time.monotonic() + 90   # let the first collection settle
    while not stop.is_set():
        mono, now = time.monotonic(), datetime.now(UTC)
        if mono >= next_minute:
            minute_jobs(engine, now)
            next_minute = mono + minute
        if mono >= next_periodic:
            periodic_jobs(engine, now)
            next_periodic = mono + periodic
        stop.wait(2.0)
