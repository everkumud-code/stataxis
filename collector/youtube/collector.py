"""Collection orchestration and normalization for YouTube observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from collector.classification import classify_video
from collector.topics import assign_topic
from collector.youtube.client import YouTubeAPIError, YouTubeClient


@dataclass(frozen=True)
class ChannelTarget:
    channel_id: str
    name: str
    language: str = "unknown"
    network: str = "unknown"
    region: str | None = None


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
    thumbnail_url: str | None = None
    category_id: str | None = None
    topic: str | None = None


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
        thumbnail_url=(
            video.get("snippet", {}).get("thumbnails", {}).get("high", {}).get("url")
            or video.get("snippet", {}).get("thumbnails", {}).get("default", {}).get("url")
        ),
        category_id=str(video.get("snippet", {}).get("categoryId")) if video.get("snippet", {}).get("categoryId") else None,
        topic=assign_topic(video.get("snippet", {}).get("title", "")),
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

@dataclass(frozen=True)
class ChannelCollection:
    observations: list[VideoObservation]
    subscribers: int | None
    total_views: int | None
    video_count: int | None
    avatar_url: str | None
    handle: str | None
    observed_at: datetime


def collect_channel_with_stats(
    client: YouTubeClient,
    target: ChannelTarget,
    max_videos: int = 25,
) -> ChannelCollection:
    """Collect a channel once while retaining its API-level channel statistics."""
    channel = client.get_channel(target.channel_id)
    uploads_id = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    uploads = client.list_uploads(uploads_id, max_results=max_videos)
    video_ids = [item.get("contentDetails", {}).get("videoId") for item in uploads.get("items", [])]
    video_ids = [video_id for video_id in video_ids if video_id]
    videos = client.get_videos(video_ids)
    observed_at = datetime.now(UTC)
    snippet = channel.get("snippet", {})
    statistics = channel.get("statistics", {})
    return ChannelCollection(
        observations=[normalize_video(video, target.channel_id, observed_at) for video in videos],
        subscribers=_integer(statistics.get("subscriberCount")),
        total_views=_integer(statistics.get("viewCount")),
        video_count=_integer(statistics.get("videoCount")),
        avatar_url=snippet.get("thumbnails", {}).get("high", {}).get("url") or snippet.get("thumbnails", {}).get("default", {}).get("url"),
        handle=str(snippet.get("customUrl")) if snippet.get("customUrl") else None,
        observed_at=observed_at,
    )


_BATCH_SIZE = 50


def _batches(items: list[str], size: int = _BATCH_SIZE):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def collect_channels_batched(
    client: YouTubeClient,
    targets: list[ChannelTarget],
    max_videos: int = 25,
) -> dict[str, ChannelCollection]:
    """Collect many channels using far fewer API units than one channel at a time.

    Every call below costs 1 quota unit:
      * channels.list   - 1 call per 50 channels (was 1 per channel)
      * playlistItems   - 1 call per channel (uploads playlist)
      * videos.list     - 1 call per 50 videos across all channels (was 1 per channel)

    For 200 channels with 25 videos each that is about 304 units per pass instead of 600.
    Results are keyed by YouTube channel ID. A channel YouTube does not return raises
    ``YouTubeAPIError``, matching the one-at-a-time behaviour.
    """
    channel_ids = list(dict.fromkeys(target.channel_id for target in targets))
    channels: dict[str, dict[str, Any]] = {}
    for batch in _batches(channel_ids):
        for item in client.get_channels(batch):
            channels[str(item.get("id", ""))] = item
    for channel_id in channel_ids:
        if channel_id not in channels:
            raise YouTubeAPIError(f"Channel not found: {channel_id}")

    video_ids_by_channel: dict[str, list[str]] = {}
    for channel_id in channel_ids:
        uploads_id = channels[channel_id]["contentDetails"]["relatedPlaylists"]["uploads"]
        uploads = client.list_uploads(uploads_id, max_results=max_videos)
        ids = [item.get("contentDetails", {}).get("videoId") for item in uploads.get("items", [])]
        video_ids_by_channel[channel_id] = [video_id for video_id in ids if video_id]

    all_video_ids = list(dict.fromkeys(vid for ids in video_ids_by_channel.values() for vid in ids))
    videos_by_id: dict[str, dict[str, Any]] = {}
    for batch in _batches(all_video_ids):
        for video in client.get_videos(batch):
            videos_by_id[str(video.get("id", ""))] = video

    observed_at = datetime.now(UTC)
    collections: dict[str, ChannelCollection] = {}
    for channel_id in channel_ids:
        channel = channels[channel_id]
        snippet = channel.get("snippet", {})
        statistics = channel.get("statistics", {})
        thumbnails = snippet.get("thumbnails", {})
        collections[channel_id] = ChannelCollection(
            observations=[
                normalize_video(videos_by_id[vid], channel_id, observed_at)
                for vid in video_ids_by_channel[channel_id]
                if vid in videos_by_id
            ],
            subscribers=_integer(statistics.get("subscriberCount")),
            total_views=_integer(statistics.get("viewCount")),
            video_count=_integer(statistics.get("videoCount")),
            avatar_url=thumbnails.get("high", {}).get("url") or thumbnails.get("default", {}).get("url"),
            handle=str(snippet.get("customUrl")) if snippet.get("customUrl") else None,
            observed_at=observed_at,
        )
    return collections
