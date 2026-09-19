"""Collection orchestration and normalization for YouTube observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from collector.classification import classify_video
from collector.youtube.client import YouTubeClient


@dataclass(frozen=True)
class ChannelTarget:
    channel_id: str
    name: str
    language: str = "unknown"
    network: str = "unknown"
    region: str = "unknown"


@dataclass(frozen=True)
class VideoObservation:
    video_id: str
    channel_id: str
    observed_at: datetime
    title: str
    published_at: str | None
    view_count: int | None
    like_count: int | None
    comment_count: int | None
    concurrent_viewers: int | None
    is_live: bool
    classification: str
    live_started_at: str | None
    live_ended_at: str | None


def _integer(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_video(
    video: dict[str, Any],
    channel_id: str,
    observed_at: datetime,
) -> VideoObservation:
    stats = video.get("statistics", {})
    live = video.get("liveStreamingDetails", {})

    classification = classify_video(video)
    is_live = classification == "LIVE"

    return VideoObservation(
        video_id=video["id"],
        channel_id=channel_id,
        observed_at=observed_at,
        title=video.get("snippet", {}).get("title", ""),
        published_at=video.get("snippet", {}).get("publishedAt"),
        view_count=_integer(stats.get("viewCount")),
        like_count=_integer(stats.get("likeCount")),
        comment_count=_integer(stats.get("commentCount")),
        concurrent_viewers=_integer(live.get("concurrentViewers")),
        is_live=is_live,
        classification=classification,
        live_started_at=live.get("actualStartTime"),
        live_ended_at=live.get("actualEndTime"),
    )


def collect_channel(
    client: YouTubeClient,
    target: ChannelTarget,
    max_videos: int = 25,
) -> list[VideoObservation]:
    """Discover recent uploads, then fetch their measurement fields in bulk."""
    channel = client.get_channel(target.channel_id)
    uploads_id = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    uploads = client.list_uploads(uploads_id, max_results=max_videos)

    video_ids = [
        item.get("contentDetails", {}).get("videoId")
        for item in uploads.get("items", [])
    ]
    video_ids = [video_id for video_id in video_ids if video_id]

    videos = client.get_videos(video_ids)
    observed_at = datetime.now(UTC)

    return [
        normalize_video(video, target.channel_id, observed_at)
        for video in videos
    ]
