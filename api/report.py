"""Channel report composition helpers for the StatAxis API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from api.channel import channel_intelligence_comparison, channel_intelligence_overview, channel_view_series
from api.signals import channel_signals


def channel_report(
    session: Session,
    channel_id: int,
    *,
    as_of: datetime | None = None,
    series_days: int = 30,
    signal_hours: int = 24,
) -> dict[str, Any] | None:
    """Compose the dashboard-ready individual channel intelligence report."""
    overview = channel_intelligence_overview(session, channel_id)
    if overview is None:
        return None

    comparison = channel_intelligence_comparison(session, channel_id, as_of=as_of)
    series = channel_view_series(session, channel_id, as_of=as_of, days=series_days)
    signals = channel_signals(session, channel_id, window_hours=signal_hours)
    resolved_as_of = comparison["as_of"] if comparison else (series or {}).get("as_of")

    return {
        "channel": {
            "channel_id": overview["channel_id"],
            "youtube_channel_id": overview.get("youtube_channel_id"),
            "name": overview["name"],
        },
        "as_of": resolved_as_of,
        "overview": overview,
        "comparison": comparison,
        "view_series": series,
        "signals": signals,
        "report_version": "v1",
    }
