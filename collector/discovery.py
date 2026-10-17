"""Finding a channel's new live streams between two collection passes.

The tracked channels are the final list. A news channel starts new live streams all day (a debate, a press conference, a special feed), and each one is tracked from its first minute as a
secondary stream: the long-running main stream is the Primary, every other stream of the channel is Secondary (see metrics/feeds.py), so a stream found here needs no label of its own.

The full collection pass looks at every channel's recent uploads only every ~107 minutes, so a new stream used to be found 49 minutes late on average (the slowest took over 17 hours). This scan is cheap:
it reads the uploads playlist of each channel that has streamed in the last 14 days (1 quota unit each, and the playlist's address is the channel id with UC changed to UU, so no extra call), looks
at the 8 newest items, and asks YouTube about only the ones StatAxis does not know yet. The ones that are live are stored at once, and the live poll takes them from there. Videos that are not live
(uploads, scheduled streams, finished streams) are left to the normal pass, so they are never marked as known before they have been properly collected.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from collector.storage import Channel, Video, save_observations
from collector.youtube.client import YouTubeAPIError, YouTubeClient
from collector.youtube.collector import normalize_video

STREAMING_DAYS = 14        # a channel is scanned when it has started a live stream within this many days
UPLOADS_PER_SCAN = 8       # the newest items of the uploads playlist looked at in each scan
VIDEO_BATCH = 50           # videos.list takes at most 50 ids
LOOKUP_CHUNK = 400


@dataclass(frozen=True)
class DiscoveryResult:
    channels: int      # channels scanned
    unknown: int       # recent items StatAxis had not seen
    added: int         # live streams stored
    errors: int        # channels whose playlist could not be read


def uploads_playlist_id(channel_id: str) -> str | None:
    """A channel's uploads playlist is its channel id with the leading UC replaced by UU; None for an id that does not follow that form."""
    return "UU" + channel_id[2:] if channel_id.startswith("UC") and len(channel_id) == 24 else None


def streaming_channels(session: Session, now: datetime, days: int = STREAMING_DAYS) -> list[Channel]:
    """Active channels that started a live stream in the last ``days`` days."""
    started = select(Video.channel_id).where(Video.live_started_at >= now - timedelta(days=days)).distinct()
    return session.query(Channel).filter(Channel.active.is_(True), Channel.id.in_(started)).order_by(Channel.id).all()


def discover_new_streams(session: Session, client: YouTubeClient, *, now: datetime | None = None, uploads_per_scan: int = UPLOADS_PER_SCAN) -> DiscoveryResult:
    """One scan. A quota error (403/429) is raised so the caller can back off; a problem with one channel only skips that channel."""
    now = now or datetime.now(UTC)
    channels = streaming_channels(session, now)
    by_youtube_id = {c.youtube_channel_id: c for c in channels}
    seen: dict[str, str] = {}   # video id -> the channel it came from
    errors = 0
    for channel in channels:
        playlist = uploads_playlist_id(channel.youtube_channel_id)
        if playlist is None:
            continue
        try:
            items = client.list_uploads(playlist, max_results=uploads_per_scan)
        except YouTubeAPIError as exc:
            if exc.status_code in (403, 429):
                raise
            errors += 1
            continue
        for item in items.get("items", []):
            video_id = (item.get("contentDetails") or {}).get("videoId")
            if video_id:
                seen.setdefault(video_id, channel.youtube_channel_id)
    ids = list(seen)
    known: set[str] = set()
    for i in range(0, len(ids), LOOKUP_CHUNK):
        known.update(v for (v,) in session.query(Video.youtube_video_id).filter(Video.youtube_video_id.in_(ids[i:i + LOOKUP_CHUNK])))
    unknown = [v for v in ids if v not in known]
    added = 0
    observed_at = datetime.now(UTC)
    for i in range(0, len(unknown), VIDEO_BATCH):
        live_by_channel: dict[str, list] = {}
        for video in client.get_videos(unknown[i:i + VIDEO_BATCH]):
            owner = seen.get(str(video.get("id", "")))
            if owner is None:
                continue
            observation = normalize_video(video, owner, observed_at)
            if observation.classification == "LIVE":
                live_by_channel.setdefault(owner, []).append(observation)
        for owner, observations in live_by_channel.items():
            channel = by_youtube_id[owner]
            added += save_observations(session=session, channel_name=channel.name, channel_youtube_id=owner, network=channel.network, language=channel.language, observations=observations,
                                       region=channel.region, segment=channel.segment)
    return DiscoveryResult(len(channels), len(unknown), added, errors)
