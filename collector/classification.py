"""Video classification vocabulary for STAXIS measurement quality."""

from enum import Enum
from typing import Any


class VideoClassification(str, Enum):
    LIVE = "LIVE"
    UPCOMING = "UPCOMING"
    COMPLETED_LIVE = "COMPLETED_LIVE"
    REGULAR_VIDEO = "REGULAR_VIDEO"
    SHORT = "SHORT"
    PREMIERE = "PREMIERE"
    REPLAY = "REPLAY"
    UNKNOWN = "UNKNOWN"


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
        return VideoClassification.REGULAR_VIDEO.value

    return VideoClassification.UNKNOWN.value
