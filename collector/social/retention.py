"""How long social figures are kept, the same rules as the YouTube figures: readings of followers and of posts are kept for at most 36 calendar months; a post's text and address are cleared when the
platform has not given them again for 30 days (the post may have been deleted or changed), and a post that has not been seen for 36 months goes with its figures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_
from sqlalchemy.orm import Session

from collector.retention import months_ago
from collector.storage import SocialPost, SocialPostStats, SocialStats

STATS_MONTHS = 36
TEXT_DAYS = 30


def run_social_retention(session: Session, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    old = months_ago(now, STATS_MONTHS)
    stale = now - timedelta(days=TEXT_DAYS)
    bulk: dict[str, Any] = {"synchronize_session": False}
    stats = session.execute(delete(SocialStats).where(SocialStats.observed_at < old), execution_options=bulk).rowcount or 0
    post_stats = session.execute(delete(SocialPostStats).where(SocialPostStats.observed_at < old), execution_options=bulk).rowcount or 0
    gone_ids = [i for (i,) in session.query(SocialPost.id).filter(or_(SocialPost.api_refreshed_at.is_(None), SocialPost.api_refreshed_at < old))]
    for i in range(0, len(gone_ids), 500):
        part = gone_ids[i:i + 500]
        session.execute(delete(SocialPostStats).where(SocialPostStats.post_id.in_(part)), execution_options=bulk)
        session.execute(delete(SocialPost).where(SocialPost.id.in_(part)), execution_options=bulk)
    cleared = (session.query(SocialPost).filter(or_(SocialPost.api_refreshed_at.is_(None), SocialPost.api_refreshed_at < stale), or_(SocialPost.text.isnot(None), SocialPost.permalink.isnot(None)))
               .update({SocialPost.text: None, SocialPost.permalink: None}, synchronize_session=False))
    session.commit()
    return {"stats_deleted": stats, "post_stats_deleted": post_stats, "post_texts_cleared": cleared or 0, "posts_deleted": len(gone_ids)}
