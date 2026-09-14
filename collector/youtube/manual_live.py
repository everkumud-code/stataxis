"""Manual live-stream targets for continuous StatAxis observation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from api.access import extract_youtube_video_id
from collector.youtube.client import YouTubeClient
from collector.youtube.collector import VideoObservation, normalize_video


@dataclass(frozen=True)
class ManualLiveTarget:
    """A user-supplied YouTube live URL with a StatAxis display name."""

    video_id: str
    display_name: str
    added_at: datetime

    @classmethod
    def from_url(cls, url: str, display_name: str) -> "ManualLiveTarget":
        name = display_name.strip()
        if not name:
            raise ValueError("display_name is required")
        return cls(
            video_id=extract_youtube_video_id(url),
            display_name=name,
            added_at=datetime.now(UTC),
        )


def fetch_manual_live(
    client: YouTubeClient,
    target: ManualLiveTarget,
) -> VideoObservation:
    """Fetch the current observation for one manually configured YouTube URL."""
    videos = client.get_videos([target.video_id])
    if not videos:
        raise ValueError("YouTube video was not found")

    video = videos[0]
    channel_id = video.get("snippet", {}).get("channelId") or "manual"
    observation = normalize_video(
        video,
        channel_id=channel_id,
        observed_at=datetime.now(UTC),
    )
    return VideoObservation(
        video_id=observation.video_id,
        channel_id=observation.channel_id,
        observed_at=observation.observed_at,
        title=target.display_name,
        published_at=observation.published_at,
        view_count=observation.view_count,
        like_count=observation.like_count,
        comment_count=observation.comment_count,
        concurrent_viewers=observation.concurrent_viewers,
        is_live=observation.is_live,
        classification=observation.classification,
        live_started_at=observation.live_started_at,
        live_ended_at=observation.live_ended_at,
    )
