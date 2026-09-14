"""Framework-neutral read-only API adapter for STX intelligence."""

from __future__ import annotations

from sqlalchemy.orm import Session

from dashboard.intelligence import build_intelligence_dashboard


def get_intelligence(session: Session, video_id: int) -> dict | None:
    """Return JSON-serializable intelligence for an API route."""
    view = build_intelligence_dashboard(session, video_id)
    if view is None:
        return None
    return view.to_dict()
