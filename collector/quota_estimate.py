"""Estimate daily YouTube Data API quota use so a bigger channel universe is planned, not guessed.

Costs (YouTube Data API v3 quota units):
  * one collection pass, per channel:  channels.list (1) + playlistItems.list (1) + videos.list (1) = 3
  * one live poll, per batch of 50 live videos: videos.list (1)
The default project quota is 10,000 units per day.
"""

from __future__ import annotations

import math
import os

UNITS_PER_CHANNEL_PASS = 3
LIVE_BATCH_SIZE = 50
DEFAULT_DAILY_QUOTA_UNITS = 10_000
SECONDS_PER_DAY = 86_400


def daily_quota_units() -> int:
    raw = os.getenv("STAXIS_YOUTUBE_DAILY_QUOTA_UNITS", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_DAILY_QUOTA_UNITS
    except ValueError:
        return DEFAULT_DAILY_QUOTA_UNITS
    return value if value > 0 else DEFAULT_DAILY_QUOTA_UNITS


def estimate_daily_units(
    channels: int,
    collect_seconds: int,
    live_poll_seconds: int,
    live_streams: int | None = None,
) -> dict[str, int]:
    """Units per day for collection passes plus live polling.

    ``live_streams`` defaults to 1.5 concurrent live streams per channel (a primary plus
    an occasional secondary feed), which is deliberately on the cautious side.
    """
    if channels < 0 or collect_seconds <= 0 or live_poll_seconds <= 0:
        raise ValueError("channels must be >= 0 and intervals must be positive")
    streams = math.ceil(channels * 1.5) if live_streams is None else live_streams
    collection = math.ceil(channels * UNITS_PER_CHANNEL_PASS * SECONDS_PER_DAY / collect_seconds)
    live = math.ceil(math.ceil(streams / LIVE_BATCH_SIZE) * SECONDS_PER_DAY / live_poll_seconds) if streams else 0
    return {"collection": collection, "live": live, "total": collection + live}


def affordable_collect_seconds(
    channels: int,
    live_poll_seconds: int,
    quota: int | None = None,
    headroom: float = 0.85,
    live_streams: int | None = None,
) -> int | None:
    """Shortest collection interval that keeps use under ``headroom`` of the quota (None if impossible)."""
    budget = (quota or daily_quota_units()) * headroom
    live = estimate_daily_units(channels, SECONDS_PER_DAY, live_poll_seconds, live_streams)["live"]
    remaining = budget - live
    if remaining <= 0 or channels == 0:
        return None if remaining <= 0 else 60
    seconds = math.ceil(channels * UNITS_PER_CHANNEL_PASS * SECONDS_PER_DAY / remaining)
    return max(60, seconds)


def quota_warning(channels: int, collect_seconds: int, live_poll_seconds: int) -> str | None:
    """A plain-language warning when the configured intervals will exhaust the daily quota."""
    quota = daily_quota_units()
    use = estimate_daily_units(channels, collect_seconds, live_poll_seconds)
    if use["total"] <= quota * 0.9:
        return None
    suggested = affordable_collect_seconds(channels, live_poll_seconds, quota)
    advice = (
        f"set COLLECT_SECONDS to {suggested} or more" if suggested
        else "live polling alone exceeds the quota; raise LIVE_POLL_SECONDS or request a higher quota"
    )
    return (
        f"YouTube quota: {channels} channels at COLLECT_SECONDS={collect_seconds} and LIVE_POLL_SECONDS="
        f"{live_poll_seconds} need about {use['total']} units/day (collection {use['collection']}, live {use['live']}) "
        f"against a {quota} unit quota; {advice}."
    )
