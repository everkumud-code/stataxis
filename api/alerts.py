"""Alerts on a channel's live audience. A person picks a channel and a rule; the collector's job loop checks the rules every minute and records an event when one is met.

Delivery today is inside StatAxis: the Alerts screen lists what fired, with a count of the ones not yet seen. There is no e-mail or phone delivery yet: it needs a sending account (SMTP or a messaging service)
configured for the server, and ``deliver`` below is the one place where it would be called.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.live_stats import FRESHNESS_SECONDS
from collector.storage import Alert, AlertEvent, Channel, Observation

KINDS = {
    "live_above": "Live viewers at or above",
    "live_below": "Live viewers at or below",
    "rise_percent": "Live viewers rise by this many percent",
    "drop_percent": "Live viewers fall by this many percent",
}
MAX_PER_PERSON = 20


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def totals_at(session: Session, at: datetime) -> dict[int, int]:
    """Each channel's live viewers (all its live streams together) as last measured within the freshness window before ``at``."""
    since = at - timedelta(seconds=FRESHNESS_SECONDS)
    latest: dict[int, tuple[datetime, int, int]] = {}
    rows = session.execute(select(Observation.channel_id, Observation.video_id, Observation.observed_at, Observation.concurrent_viewers)
                           .where(Observation.is_live.is_(True), Observation.concurrent_viewers.is_not(None), Observation.observed_at > since, Observation.observed_at <= at))
    for channel_id, video_id, observed_at, viewers in rows:
        if video_id not in latest or observed_at > latest[video_id][0]:
            latest[video_id] = (observed_at, channel_id, int(viewers))
    totals: dict[int, int] = {}
    for _t, channel_id, viewers in latest.values():
        totals[channel_id] = totals.get(channel_id, 0) + viewers
    return totals


def deliver(session: Session, event: AlertEvent) -> None:
    """Where an alert reaches the person. In StatAxis it is the event itself (shown on the Alerts screen). E-mail or phone delivery would be called from here once a sending account is configured."""


def evaluate_alerts(session: Session, *, now: datetime | None = None) -> int:
    """Check every active alert once. Returns how many fired."""
    now = now or datetime.now(UTC)
    alerts = session.query(Alert).filter(Alert.active.is_(True)).all()
    if not alerts:
        return 0
    current = totals_at(session, now)
    earlier: dict[int, dict[int, int]] = {}
    names = {cid: name for cid, name in session.query(Channel.id, Channel.name)}
    fired = 0
    for alert in alerts:
        value = current.get(alert.channel_id)
        if value is None:
            continue
        if alert.last_fired_at is not None and (now - _aware(alert.last_fired_at)).total_seconds() < alert.cooldown_minutes * 60:
            continue
        name, message = names.get(alert.channel_id, "channel"), None
        if alert.kind == "live_above" and value >= alert.threshold:
            message = f"{name} has {value:,} live viewers, at or above your {alert.threshold:,.0f}."
        elif alert.kind == "live_below" and value <= alert.threshold:
            message = f"{name} has {value:,} live viewers, at or below your {alert.threshold:,.0f}."
        elif alert.kind in ("rise_percent", "drop_percent"):
            if alert.window_minutes not in earlier:
                earlier[alert.window_minutes] = totals_at(session, now - timedelta(minutes=alert.window_minutes))
            before = earlier[alert.window_minutes].get(alert.channel_id)
            if before and before >= 200:
                change = 100.0 * (value - before) / before
                if alert.kind == "rise_percent" and change >= alert.threshold:
                    message = f"{name} went up {change:.0f}% in {alert.window_minutes} minutes, from {before:,} to {value:,} live viewers."
                elif alert.kind == "drop_percent" and -change >= alert.threshold:
                    message = f"{name} fell {-change:.0f}% in {alert.window_minutes} minutes, from {before:,} to {value:,} live viewers."
        if message:
            event = AlertEvent(alert_id=alert.id, user_id=alert.user_id, channel_id=alert.channel_id, fired_at=now, value=float(value), message=message)
            session.add(event)
            alert.last_fired_at = now
            deliver(session, event)
            fired += 1
    session.commit()
    return fired


def _row(a: Alert, names: dict[int, str]) -> dict[str, Any]:
    return {"id": a.id, "channel_id": a.channel_id, "channel": names.get(a.channel_id, "?"), "kind": a.kind, "kind_label": KINDS.get(a.kind, a.kind), "threshold": a.threshold,
            "window_minutes": a.window_minutes, "cooldown_minutes": a.cooldown_minutes, "active": a.active, "last_fired_at": a.last_fired_at.isoformat() if a.last_fired_at else None}


def list_alerts(session: Session, user_id: int) -> dict[str, Any]:
    names = {cid: name for cid, name in session.query(Channel.id, Channel.name)}
    alerts = session.query(Alert).filter(Alert.user_id == user_id).order_by(Alert.id).all()
    events = session.query(AlertEvent).filter(AlertEvent.user_id == user_id).order_by(AlertEvent.fired_at.desc()).limit(50).all()
    return {"alerts": [_row(a, names) for a in alerts], "kinds": KINDS, "unseen": sum(1 for e in events if not e.seen), "max": MAX_PER_PERSON,
            "events": [{"id": e.id, "alert_id": e.alert_id, "channel": names.get(e.channel_id, "?"), "fired_at": e.fired_at.isoformat(), "message": e.message, "seen": e.seen} for e in events],
            "delivery": "Alerts appear here, inside StatAxis. E-mail and phone delivery are not set up yet."}


def create_alert(session: Session, user_id: int, *, channel_id: Any, kind: str, threshold: Any, window_minutes: Any = 10, cooldown_minutes: Any = 60) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError("choose one of: " + ", ".join(KINDS))
    try:
        channel = session.get(Channel, int(channel_id))
        threshold = float(threshold)
        window_minutes, cooldown_minutes = int(window_minutes), int(cooldown_minutes)
    except (TypeError, ValueError) as exc:
        raise ValueError("the channel, the threshold and the minutes must be numbers") from exc
    if channel is None or not channel.active:
        raise ValueError("choose a channel that is being measured")
    if threshold <= 0 or threshold > (1000 if kind.endswith("percent") else 10_000_000):
        raise ValueError("the threshold is out of range")
    if not 5 <= window_minutes <= 120 or not 5 <= cooldown_minutes <= 1440:
        raise ValueError("the window must be 5 to 120 minutes and the pause 5 to 1440 minutes")
    if session.query(Alert).filter(Alert.user_id == user_id).count() >= MAX_PER_PERSON:
        raise ValueError(f"you can keep up to {MAX_PER_PERSON} alerts")
    alert = Alert(user_id=user_id, channel_id=channel.id, kind=kind, threshold=threshold, window_minutes=window_minutes, cooldown_minutes=cooldown_minutes)
    session.add(alert)
    session.commit()
    return _row(alert, {channel.id: channel.name})


def own_alert(session: Session, user_id: int, alert_id: Any) -> Alert:
    alert = session.get(Alert, int(alert_id))
    if alert is None or alert.user_id != user_id:
        raise LookupError("alert not found")
    return alert


def delete_alert(session: Session, user_id: int, alert_id: Any) -> None:
    alert = own_alert(session, user_id, alert_id)
    session.query(AlertEvent).filter(AlertEvent.alert_id == alert.id).delete(synchronize_session=False)
    session.delete(alert)
    session.commit()


def toggle_alert(session: Session, user_id: int, alert_id: Any, active: bool) -> None:
    own_alert(session, user_id, alert_id).active = bool(active)
    session.commit()


def mark_seen(session: Session, user_id: int) -> None:
    session.query(AlertEvent).filter(AlertEvent.user_id == user_id, AlertEvent.seen.is_(False)).update({"seen": True}, synchronize_session=False)
    session.commit()
