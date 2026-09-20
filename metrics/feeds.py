"""Primary / secondary / all live-feed split for a publisher's concurrent streams.

Definitions (STAXIS product terms):
  Primary feed    the publisher's long-running live stream (24x7 style); it stays live
                  for a very long time.
  Secondary feeds event-based or parallel streams that run alongside the primary feed
                  and end when the event ends.
  All feed        primary + every secondary feed (every concurrent live stream).

Classification is done from YouTube's actual start time so it needs no manual tagging:
among a channel's concurrently live streams, the one that has been live the longest
(and at least ``min_primary_hours``, default 30 days) is the primary feed; every other live stream is a
secondary feed. If nothing has been live long enough there is no primary feed at that
moment and all concurrent viewers are reported as secondary, so the All feed is never
understated.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Sequence

DEFAULT_MIN_PRIMARY_HOURS = 30 * 24.0  # primary feed = live for 30 days or more


def min_primary_hours() -> float:
    raw = os.getenv("STAXIS_PRIMARY_MIN_LIVE_HOURS", "").strip()
    try:
        value = float(raw) if raw else DEFAULT_MIN_PRIMARY_HOURS
    except ValueError:
        return DEFAULT_MIN_PRIMARY_HOURS
    return value if value >= 0 else DEFAULT_MIN_PRIMARY_HOURS


@dataclass(frozen=True)
class LiveStream:
    video_id: str | int
    concurrent_viewers: int
    started_at: datetime | None


@dataclass(frozen=True)
class FeedSplit:
    primary: int
    secondary: int
    all: int
    primary_video_id: str | int | None
    secondary_count: int
    min_primary_hours: float

    def as_dict(self) -> dict[str, object]:
        return {
            "primary": self.primary,
            "secondary": self.secondary,
            "all": self.all,
            "primary_video_id": self.primary_video_id,
            "secondary_count": self.secondary_count,
            "primary_min_live_hours": self.min_primary_hours,
        }


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def split_feeds(
    streams: Sequence[LiveStream],
    *,
    now: datetime,
    min_hours: float | None = None,
) -> FeedSplit:
    """Split one channel's concurrent live streams into primary / secondary / all."""
    threshold = min_primary_hours() if min_hours is None else min_hours
    current = _utc(now)
    total = sum(max(0, int(stream.concurrent_viewers or 0)) for stream in streams)

    eligible = [
        stream for stream in streams
        if stream.started_at is not None
        and (current - _utc(stream.started_at)).total_seconds() >= threshold * 3600
    ]
    if not eligible:
        return FeedSplit(0, total, total, None, len(streams), threshold)

    primary = min(
        eligible,
        key=lambda stream: (_utc(stream.started_at), -int(stream.concurrent_viewers or 0), str(stream.video_id)),
    )
    primary_viewers = max(0, int(primary.concurrent_viewers or 0))
    return FeedSplit(
        primary=primary_viewers,
        secondary=total - primary_viewers,
        all=total,
        primary_video_id=primary.video_id,
        secondary_count=len(streams) - 1,
        min_primary_hours=threshold,
    )
