"""Daily and weekly notes: the findings engine (api/findings.py) writes one on a schedule and keeps it, so there is a dated record of what the data said that day or that week."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from api.findings import briefing
from api.market_common import IST
from collector.storage import Note

KINDS = {"daily": 3, "weekly": 7}   # the window of days each kind looks back over


def generate_note(session: Session, kind: str, for_date: date, *, now: datetime | None = None) -> bool:
    """Write the note of ``kind`` for ``for_date`` unless it already exists. Returns True when a note was written."""
    if kind not in KINDS:
        raise ValueError("kind must be daily or weekly")
    if session.query(Note).filter_by(kind=kind, for_date=for_date.isoformat()).first():
        return False
    b = briefing(session, persona="media", days=KINDS[kind], now=now)
    findings = [{"headline": f["headline"], "detail": f["detail"], "confidence": f["confidence"], "so_what": f["so_what"], "evidence": f["evidence"]} for f in b["findings"][:6]]
    if not findings:
        return False   # nothing measured yet: no note is better than an empty one
    title = f"Daily note, {for_date.day} {for_date:%B %Y}" if kind == "daily" else f"Weekly note, week to {for_date.day} {for_date:%B %Y}"
    body = {"window": b["window"], "kpis": b["kpis"], "findings": findings, "generated_at": (now or datetime.now(UTC)).isoformat(),
            "how": "Written by the StatAxis findings engine from the stored measurements; every sentence rests on the evidence shown with it."}
    session.add(Note(kind=kind, for_date=for_date.isoformat(), title=title, body_json=json.dumps(body, default=str)))
    session.commit()
    return True


def due_notes(now: datetime) -> list[tuple[str, date]]:
    """Notes that should exist by now: the day's note from 09:00 IST, and on Mondays the week's note."""
    local = now.astimezone(IST)
    if local.hour < 9:
        return []
    due = [("daily", local.date())]
    if local.weekday() == 0:
        due.append(("weekly", local.date()))
    return due


def list_notes(session: Session, *, limit: int = 30) -> list[dict[str, Any]]:
    rows = session.query(Note).order_by(Note.for_date.desc(), Note.kind.asc()).limit(max(1, min(int(limit), 100))).all()
    return [{"id": r.id, "kind": r.kind, "date": r.for_date, "title": r.title, "created_at": r.created_at.isoformat(), **json.loads(r.body_json or "{}")} for r in rows]
