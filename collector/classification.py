"""Video classification vocabulary for STAXIS measurement quality."""

import re
from datetime import UTC, datetime
from enum import Enum
from typing import Any

# YouTube Help ("Understand three-minute YouTube Shorts"): since 15 Oct 2024 a square or
# vertical video of up to three minutes is a Short; before that the limit was one minute.
# The Data API has no isShort flag and does not expose aspect ratio, so STAXIS classifies
# on duration (and this upload-date rule).
SHORT_MAX_SECONDS = 180
LEGACY_SHORT_MAX_SECONDS = 60
SHORTS_EXTENDED_FROM = datetime(2024, 10, 15, tzinfo=UTC)

_DURATION_RE = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


class VideoClassification(str, Enum):
    LIVE = "LIVE"
    UPCOMING = "UPCOMING"
    COMPLETED_LIVE = "COMPLETED_LIVE"
    REGULAR_VIDEO = "REGULAR_VIDEO"
    SHORT = "SHORT"
    PREMIERE = "PREMIERE"
    REPLAY = "REPLAY"
    UNKNOWN = "UNKNOWN"


def parse_iso8601_duration_seconds(value: Any) -> int | None:
    """Parse a YouTube ISO 8601 duration such as PT1M15S; None when absent or malformed."""
    if not isinstance(value, str):
        return None
    match = _DURATION_RE.match(value.strip())
    if match is None or not any(match.groups()):
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _published_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def is_short_duration(duration_seconds: int | None, published_at: Any = None) -> bool:
    """True when the duration is within the Shorts limit that applied at upload time."""
    if duration_seconds is None or duration_seconds <= 0:
        return False
    published = _published_at(published_at)
    limit = LEGACY_SHORT_MAX_SECONDS if published is not None and published < SHORTS_EXTENDED_FROM else SHORT_MAX_SECONDS
    return duration_seconds <= limit


def classify_video(video: dict[str, Any]) -> str:
    """Classify a YouTube video using public API metadata."""
    snippet = video.get("snippet", {})
    live_details = video.get("liveStreamingDetails", {})
    live_broadcast_content = snippet.get("liveBroadcastContent")
    actual_start = live_details.get("actualStartTime")
    actual_end = live_details.get("actualEndTime")

    # Active broadcasts are identifiable from an actual start with no actual end.
    # This remains reliable when liveBroadcastContent is omitted by a client or fixture.
    if actual_start and not actual_end and live_broadcast_content in (None, "live"):
        return VideoClassification.LIVE.value

    if live_broadcast_content == "upcoming" and not actual_start:
        return VideoClassification.UPCOMING.value

    if actual_start and actual_end:
        return VideoClassification.COMPLETED_LIVE.value

    if live_broadcast_content == "none":
        duration = parse_iso8601_duration_seconds(video.get("contentDetails", {}).get("duration"))
        if is_short_duration(duration, snippet.get("publishedAt")):
            return VideoClassification.SHORT.value
        return VideoClassification.REGULAR_VIDEO.value

    return VideoClassification.UNKNOWN.value
