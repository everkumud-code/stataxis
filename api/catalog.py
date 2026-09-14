"""Read-only catalog endpoints for dashboard discovery."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from collector.storage import Channel


def list_channels(session: Session) -> list[dict[str, Any]]:
    """Return active channels in stable display order."""
    stmt = (
        select(Channel)
        .where(Channel.active.is_(True))
        .order_by(Channel.name.asc())
    )
    return [
        {
            "id": channel.id,
            "youtube_channel_id": channel.youtube_channel_id,
            "name": channel.name,
            "network": channel.network,
            "language": channel.language,
            "region": channel.region,
        }
        for channel in session.scalars(stmt)
    ]
