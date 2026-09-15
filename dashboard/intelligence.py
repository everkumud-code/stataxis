"""Read-only dashboard adapter for persisted STX intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from api.intelligence import latest_video_intelligence


@dataclass(frozen=True)
class IntelligenceDashboard:
    """JSON-ready dashboard representation of one persisted snapshot."""

    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


def build_intelligence_dashboard(
    session: Session,
    video_id: int,
) -> IntelligenceDashboard | None:
    """Return the latest persisted intelligence, without recomputing metrics."""
    payload = latest_video_intelligence(session, video_id)
    if payload is None:
        return None
    return IntelligenceDashboard(payload)
