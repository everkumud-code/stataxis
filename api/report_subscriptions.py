"""Report e-mails: a person chooses how often, in which layout and with which parts, and StatAxis sends the report to the address of their own login.

  * Only the signed-in person can subscribe, and only to their own e-mail address (nobody can sign someone else up). Every e-mail carries a one-click unsubscribe link.
  * The collector's job loop calls ``send_due`` every ten minutes: for each active subscription whose send day has come (api/report_content.period_for) and whose hour (Indian time) has passed, the
    report for the period just ended is built once for everybody who asked for the same thing, drawn as a one-pager or a booklet (api/report_layouts.py) and e-mailed through Resend (api/mailer.py).
  * A period is sent once (a unique delivery record). When StatAxis has not measured enough of the period, the delivery says 'waiting for history'; when no mail key is set, 'waiting for a mail key'.
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api import mailer
from api.report_content import INTERVALS, NotEnoughHistory, build_content, period_for
from api.report_layouts import ALL_SECTIONS, ONE_PAGER_SECTIONS, booklet, one_pager
from api.stamps import IST
from collector.storage import ReportDelivery, ReportSubscription, User

logger = logging.getLogger(__name__)
LAYOUTS = {"one_pager": "One-pager", "booklet": "Booklet"}
SECTION_LABELS = {"highlights": "Highlights (what stands out)", "findings": "Detailed findings", "data": "Data (tables and trend)", "observations": "Observations", "viewpoint": "StatAxis viewpoint"}
MAX_PER_PERSON = 12
MANUAL_PER_HOUR = 4


def options() -> dict[str, Any]:
    return {"intervals": [{"id": k, "label": v["label"]} for k, v in INTERVALS.items()], "layouts": [{"id": k, "label": v} for k, v in LAYOUTS.items()],
            "sections": [{"id": k, "label": SECTION_LABELS[k], "default_one_pager": k in ONE_PAGER_SECTIONS} for k in ALL_SECTIONS],
            "note": "The STX Index and the key numbers are always in the report. Reports go to the e-mail address of your login."}


def _row(sub: ReportSubscription, last: ReportDelivery | None) -> dict[str, Any]:
    return {"id": sub.id, "interval": sub.interval, "interval_label": INTERVALS[sub.interval]["label"], "layout": sub.layout, "layout_label": LAYOUTS.get(sub.layout, sub.layout),
            "sections": json.loads(sub.sections_json or "[]") or list(ONE_PAGER_SECTIONS if sub.layout == "one_pager" else ALL_SECTIONS), "language": sub.language, "segment": sub.segment, "send_hour": sub.send_hour, "active": sub.active,
            "last": {"status": last.status, "period": last.period_label, "at": last.created_at.isoformat(), "detail": last.detail} if last else None}


def list_subscriptions(session: Session, user: User) -> dict[str, Any]:
    subs = session.query(ReportSubscription).filter(ReportSubscription.user_id == user.id).order_by(ReportSubscription.id).all()
    out = []
    for s in subs:
        last = session.query(ReportDelivery).filter(ReportDelivery.subscription_id == s.id).order_by(ReportDelivery.id.desc()).first()
        out.append(_row(s, last))
    return {"email": user.email, "subscriptions": out, "options": options(), "mail_ready": mailer.public_status(session)["configured"]}


def _clean(interval: Any, layout: Any, sections: Any, language: Any, segment: Any, send_hour: Any) -> dict[str, Any]:
    if interval not in INTERVALS:
        raise ValueError("choose how often: " + ", ".join(INTERVALS))
    if layout not in LAYOUTS:
        raise ValueError("choose a layout: one-pager or booklet")
    chosen = [x for x in (sections or []) if x in ALL_SECTIONS] if isinstance(sections, list) else []
    try:
        hour = int(send_hour if send_hour not in (None, "") else 8)
    except (TypeError, ValueError) as exc:
        raise ValueError("choose an hour between 0 and 23") from exc
    if not 0 <= hour <= 23:
        raise ValueError("choose an hour between 0 and 23")
    return {"interval": interval, "layout": layout, "sections_json": json.dumps(chosen), "language": str(language).strip()[:32] or None if language else None, "segment": str(segment).strip()[:32] or None if segment else None, "send_hour": hour}


def save_subscription(session: Session, user: User, *, sub_id: Any = None, interval: Any, layout: Any, sections: Any = None, language: Any = None, segment: Any = None, send_hour: Any = None) -> dict[str, Any]:
    fields = _clean(interval, layout, sections, language, segment, send_hour)
    if sub_id:
        sub = session.get(ReportSubscription, int(sub_id))
        if sub is None or sub.user_id != user.id:
            raise LookupError("subscription not found")
    else:
        if session.query(ReportSubscription).filter(ReportSubscription.user_id == user.id).count() >= MAX_PER_PERSON:
            raise ValueError(f"at most {MAX_PER_PERSON} report subscriptions each")
        if session.query(ReportSubscription).filter(ReportSubscription.user_id == user.id, ReportSubscription.interval == fields["interval"], ReportSubscription.layout == fields["layout"],
                                                    ReportSubscription.language == fields["language"], ReportSubscription.segment == fields["segment"]).first():
            raise ValueError("you already have this report: change it instead")
        sub = ReportSubscription(user_id=user.id, unsubscribe_token=secrets.token_urlsafe(24))
        session.add(sub)
    for k, v in fields.items():
        setattr(sub, k, v)
    sub.active = True
    session.commit()
    return list_subscriptions(session, user)


def set_active(session: Session, user: User, sub_id: Any, active: bool) -> dict[str, Any]:
    sub = session.get(ReportSubscription, int(sub_id))
    if sub is None or sub.user_id != user.id:
        raise LookupError("subscription not found")
    sub.active = bool(active)
    session.commit()
    return list_subscriptions(session, user)


def delete_subscription(session: Session, user: User, sub_id: Any) -> dict[str, Any]:
    sub = session.get(ReportSubscription, int(sub_id))
    if sub is None or sub.user_id != user.id:
        raise LookupError("subscription not found")
    session.query(ReportDelivery).filter(ReportDelivery.subscription_id == sub.id).delete()
    session.delete(sub)
    session.commit()
    return list_subscriptions(session, user)


def unsubscribe(session: Session, token: str) -> bool:
    """The one-click link in every e-mail: switches that subscription off. True when a subscription was found."""
    sub = session.query(ReportSubscription).filter(ReportSubscription.unsubscribe_token == str(token or "")).first() if token else None
    if sub is None:
        return False
    sub.active = False
    session.commit()
    return True


# ------------------------------------------------------------------------------------------------ the e-mail
def sections_of(sub: ReportSubscription) -> list[str]:
    chosen = json.loads(sub.sections_json or "[]")
    return chosen or list(ONE_PAGER_SECTIONS if sub.layout == "one_pager" else ALL_SECTIONS)


def email_parts(content: dict[str, Any], sub: ReportSubscription, base_url: str) -> tuple[str, str, str]:
    """(subject, html, text) for one report: the STX Index first, the top of the ranking, our viewpoint, and the links."""
    stx = content.get("stx")
    subject = f"StatAxis {INTERVALS[sub.interval]['label'].lower()}: {content['period']}" + (f" · STX leader {stx['leader']} {stx['leader_score']:.1f}" if stx else "")
    unsub = f"{base_url}/unsubscribe?token={sub.unsubscribe_token}"
    rows = "".join(f"<tr><td style='padding:6px 10px;color:#0b8ded'>{r['rank']:02d}</td><td style='padding:6px 10px;color:#fdfdfd'>{escape(r['name'])}</td><td style='padding:6px 10px;color:#0b8ded;font-weight:700;text-align:right'>{'-' if r.get('stx') is None else format(r['stx'], '.1f')}</td>"
                   f"<td style='padding:6px 10px;color:#ccd5dd;text-align:right'>{r['views']:,.1f}M</td></tr>" for r in content["ranking"][:5])
    box = (f"<div style='border:1px solid #0b8ded;border-radius:10px;padding:14px 16px;margin:16px 0;background:#050d17'><div style='font:12px monospace;letter-spacing:3px;color:#0b8ded'>STX INDEX</div>"
           f"<div style='font-size:19px;font-weight:700;color:#fdfdfd;margin-top:6px'>Highest: {escape(stx['leader'])} · {stx['leader_score']:.1f}</div><div style='color:#9ba0a6;margin-top:4px;font-size:13px'>Average of {stx['scored']} scored channels: {stx['average']:.1f}</div></div>") if stx else ""
    html = (f"<div style='background:#010509;padding:24px 12px;font-family:Segoe UI,Arial,sans-serif'><div style='max-width:620px;margin:auto;background:#010509;color:#ccd5dd'>"
            f"<div style='font:12px monospace;letter-spacing:3px;color:#9ba0a6'><span style='color:#0b8ded'>●</span> FIG. 00 · {escape(INTERVALS[sub.interval]['label'].upper())}</div>"
            f"<h1 style='margin:10px 0 2px;font:800 28px Impact,Arial Narrow,Arial,sans-serif;color:#fdfdfd;text-transform:uppercase'>{escape(content['title'])}</h1><div style='color:#0b8ded;font-size:15px'>{escape(content['period'])}</div>{box}"
            f"<table style='width:100%;border-collapse:collapse;font-size:14px'><tr style='background:#0b52b1;color:#fff'><th style='padding:7px 10px;text-align:left'>#</th><th style='padding:7px 10px;text-align:left'>Channel</th><th style='padding:7px 10px;text-align:right'>STX</th><th style='padding:7px 10px;text-align:right'>Views</th></tr>{rows}</table>"
            f"<p style='font:italic 18px Georgia,serif;color:#0b8ded;line-height:1.5;margin:18px 0'>{escape(content['viewpoint'])}</p>"
            f"<p style='font-size:13px;color:#9ba0a6'>The full {escape(LAYOUTS[sub.layout].lower())} is attached as a PDF. <a href='{base_url}/workspace' style='color:#0b8ded'>Open StatAxis</a> to see more.</p>"
            f"<hr style='border:0;border-top:1px solid #255073;margin:18px 0'><p style='font-size:12px;color:#9ba0a6'>Data via YouTube. Processed and evaluated by StatAxis. Not TV ratings. stataxis.org · x.com/stataxis<br>"
            f"You get this because you chose it in StatAxis. <a href='{unsub}' style='color:#9ba0a6'>Unsubscribe</a></p></div></div>")
    text = (f"{content['title']} - {content['period']}\n" + (f"STX Index: {stx['leader']} is highest at {stx['leader_score']:.1f}; average {stx['average']:.1f}.\n" if stx else "") + "\n"
            + "\n".join(f"{r['rank']:02d}  {r['name']}  STX {'-' if r.get('stx') is None else format(r['stx'], '.1f')}  {r['views']:,.1f}M" for r in content["ranking"][:5]) + f"\n\n{content['viewpoint']}\n\nThe full report is attached as a PDF.\nUnsubscribe: {unsub}\n")
    return subject, html, text


def _send(session: Session, sub: ReportSubscription, user: User, content: dict[str, Any]) -> str:
    cfg = mailer.settings(session)
    subject, html, text = email_parts(content, sub, cfg["base_url"])
    pdf = (booklet if sub.layout == "booklet" else one_pager)(content, prepared_for=user.email, sections=sections_of(sub))
    name = f"stataxis-{sub.interval}-{sub.layout.replace('_', '-')}-{content['period'].split(' (')[0].replace(' ', '-').replace('–', 'to')}.pdf"
    return mailer.send_email(session, to=user.email, subject=subject, html=html, text=text, attachments=[(name, pdf)], unsubscribe_url=f"{cfg['base_url']}/unsubscribe?token={sub.unsubscribe_token}")


def _record(session: Session, sub: ReportSubscription, period_key: str, label: str, status: str, detail: str = "", message_id: str | None = None, trigger: str = "scheduled") -> bool:
    session.add(ReportDelivery(subscription_id=sub.id, period_key=period_key, period_label=label, trigger=trigger, status=status, detail=detail[:400], message_id=message_id))
    try:
        session.commit()
        return True
    except IntegrityError:
        session.rollback()
        return False


def send_due(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Send every report that is due. Safe to call often: a period is recorded once per subscription, and one that is waiting is tried again on the next call."""
    now = now or datetime.now(UTC)
    local = now.astimezone(IST)
    counts = {"sent": 0, "waiting_history": 0, "waiting_key": 0, "failed": 0}
    subs = session.query(ReportSubscription).filter(ReportSubscription.active.is_(True)).all()
    built: dict[tuple, dict[str, Any] | None] = {}
    ready = mailer.public_status(session)["configured"]
    for sub in subs:
        if sub.interval not in INTERVALS:
            continue
        period = period_for(sub.interval, local.date())
        if period is None or local.hour < sub.send_hour:
            continue
        key = f"{sub.interval}:{period[0]}:{period[1]}"
        existing = session.query(ReportDelivery).filter(ReportDelivery.subscription_id == sub.id, ReportDelivery.period_key == key, ReportDelivery.trigger == "scheduled").first()
        if existing is not None and existing.status in ("sent", "failed"):
            continue
        user = session.get(User, sub.user_id)
        if user is None or not user.active:
            continue
        if not ready:
            counts["waiting_key"] += 1
            continue                                        # not recorded: tried again as soon as a key is set
        ck = (sub.interval, period, sub.language, sub.segment)
        if ck not in built:
            try:
                built[ck] = build_content(session, sub.interval, period[0], period[1], language=sub.language, segment=sub.segment)
            except NotEnoughHistory as exc:
                built[ck] = None
                logger.info("report %s waits for history: %s", key, exc)
        content = built[ck]
        if content is None:
            if existing is None:
                _record(session, sub, key, key, "waiting_history", "StatAxis has not measured enough of this period yet")
            counts["waiting_history"] += 1
            continue
        try:
            message_id = _send(session, sub, user, content)
        except (mailer.MailError, ValueError, OSError) as exc:
            if existing is not None:
                existing.status, existing.detail = "failed", str(exc)[:400]
                session.commit()
            else:
                _record(session, sub, key, content["period"], "failed", str(exc))
            counts["failed"] += 1
            continue
        if existing is not None:
            existing.status, existing.period_label, existing.message_id, existing.detail = "sent", content["period"], message_id, ""
            session.commit()
        else:
            _record(session, sub, key, content["period"], "sent", "", message_id)
        counts["sent"] += 1
    return counts


def send_now(session: Session, user: User, sub_id: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """'Send me this report now': the latest finished period of this subscription, to the person's own address (a few times an hour at most)."""
    sub = session.get(ReportSubscription, int(sub_id))
    if sub is None or sub.user_id != user.id:
        raise LookupError("subscription not found")
    now = now or datetime.now(UTC)
    recent = session.query(ReportDelivery).join(ReportSubscription, ReportSubscription.id == ReportDelivery.subscription_id).filter(
        ReportSubscription.user_id == user.id, ReportDelivery.trigger == "manual", ReportDelivery.created_at > now - timedelta(hours=1)).count()
    if recent >= MANUAL_PER_HOUR:
        raise ValueError("you asked for several reports in the last hour: please wait a little")
    local = now.astimezone(IST).date()
    period = None
    for back in range(0, 400):                               # the latest period that has ended: walk back to the last send day of this interval
        period = period_for(sub.interval, local - timedelta(days=back))
        if period:
            break
    if period is None:
        raise ValueError("no period to report yet")
    try:
        content = build_content(session, sub.interval, period[0], period[1], language=sub.language, segment=sub.segment)
    except NotEnoughHistory as exc:
        raise ValueError(f"not yet: {exc}") from exc
    try:
        message_id = _send(session, sub, user, content)
    except mailer.MailError as exc:
        raise ValueError(str(exc)) from exc
    key = f"{sub.interval}:{period[0]}:{period[1]}:{secrets.token_hex(4)}"   # a request on demand is its own record, however many there are
    _record(session, sub, key, content["period"], "sent", "sent on request", message_id, trigger="manual")
    return {"sent_to": user.email, "period": content["period"]}
