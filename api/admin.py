from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from api.access import extract_youtube_video_id
from api.auth import AuthIdentity
from collector.storage import Channel, ChannelLanguageOverride, Observation, Video
from collector.youtube.client import YouTubeClient
from collector.youtube.manual_live import ManualLiveTarget, fetch_manual_live


def require_admin(identity: AuthIdentity) -> None:
    if not identity.is_admin:
        raise PermissionError("admin access required")


def add_channel(session: Session, identity: AuthIdentity, url: str, display_name: str, language: str, region: str, market: str, *, client: YouTubeClient | None = None) -> dict[str, object]:
    require_admin(identity)
    normalized_url = url.strip()
    normalized_name = display_name.strip()
    normalized_language = language.strip()
    normalized_region = region.strip() or "unknown"
    normalized_market = market.strip() or "unknown"
    if not normalized_url:
        raise ValueError("channel URL is required")
    if not normalized_name:
        raise ValueError("display_name is required")
    if not normalized_language:
        raise ValueError("language is required")
    if len(normalized_name) > 255 or len(normalized_language) > 100 or len(normalized_region) > 100 or len(normalized_market) > 255:
        raise ValueError("channel metadata is too long")
    owns_client = client is None
    youtube = client or YouTubeClient()
    try:
        meta = youtube.resolve_channel_url(normalized_url)
        channel_id = str(meta.get("id") or "").strip()
        if not channel_id:
            raise ValueError("YouTube did not return a channel ID")
        snippet = meta.get("snippet", {})
        channel = session.query(Channel).filter_by(youtube_channel_id=channel_id).one_or_none()
        if channel is None:
            channel = Channel(
                youtube_channel_id=channel_id,
                name=normalized_name,
                network=normalized_market,
                language=normalized_language,
                region=normalized_region,
                active=True,
            )
            session.add(channel)
            session.flush()
            existing = False
        else:
            channel.name = normalized_name
            channel.network = normalized_market
            channel.language = normalized_language
            channel.region = normalized_region
            channel.active = True
            existing = True
        session.commit()
        return {
            "channel_id": channel.id,
            "youtube_channel_id": channel.youtube_channel_id,
            "name": channel.name,
            "youtube_name": str(snippet.get("title") or channel.name),
            "language": channel.language,
            "region": channel.region,
            "market": channel.network,
            "active": channel.active,
            "existing": existing,
        }
    finally:
        if owns_client:
            youtube.close()


def rename_channel(session: Session, identity: AuthIdentity, channel_id: int, display_name: str) -> dict[str, object]:
    require_admin(identity)
    if channel_id <= 0:
        raise ValueError("channel_id must be positive")
    normalized = display_name.strip()
    if not normalized or len(normalized) > 255:
        raise ValueError("display_name is required and must be <= 255 characters")
    channel = session.get(Channel, channel_id)
    if channel is None:
        raise LookupError("channel not found")
    channel.name = normalized
    session.commit()
    return {"channel_id": channel.id, "name": channel.name}


def add_video(session: Session, identity: AuthIdentity, url: str, display_name: str, *, client: YouTubeClient | None = None) -> dict[str, object]:
    require_admin(identity)
    youtube_id = extract_youtube_video_id(url)
    existing = session.query(Video).filter_by(youtube_video_id=youtube_id).one_or_none()
    if existing is not None:
        channel = session.query(Channel).filter_by(id=existing.channel_id).one()
        return {"video_id": existing.id, "youtube_video_id": existing.youtube_video_id, "display_name": existing.title, "channel_id": channel.id, "channel_name": channel.name, "existing": True}
    target = ManualLiveTarget.from_url(url, display_name)
    owns_client = client is None
    youtube = client or YouTubeClient()
    try:
        observation = fetch_manual_live(youtube, target)
        meta = youtube.get_channel(observation.channel_id)
        snippet = meta.get("snippet", {})
        channel = session.query(Channel).filter_by(youtube_channel_id=observation.channel_id).one_or_none()
        if channel is None:
            channel = Channel(youtube_channel_id=observation.channel_id, name=str(snippet.get("title") or observation.channel_id), network=str(snippet.get("customUrl") or "unknown"), language=str(snippet.get("defaultLanguage") or "unknown"), region="unknown", active=True)
            session.add(channel)
            session.flush()
        else:
            channel.active = True
        video = Video(youtube_video_id=observation.video_id, channel_id=channel.id, title=display_name.strip(), published_at=observation.published_at)
        session.add(video)
        session.flush()
        session.add(Observation(video_id=video.id, channel_id=channel.id, observed_at=observation.observed_at, view_count=observation.view_count, like_count=observation.like_count, comment_count=observation.comment_count, concurrent_viewers=observation.concurrent_viewers, is_live=observation.is_live, classification=observation.classification))
        session.commit()
        return {"video_id": video.id, "youtube_video_id": video.youtube_video_id, "display_name": video.title, "channel_id": channel.id, "channel_name": channel.name, "existing": False}
    finally:
        if owns_client:
            youtube.close()


def remove_video(session: Session, identity: AuthIdentity, video_id: int) -> None:
    require_admin(identity)
    if video_id <= 0:
        raise ValueError("video_id must be a positive integer")
    video = session.query(Video).filter_by(id=video_id).one_or_none()
    if video is None:
        raise LookupError("video not found")
    session.query(Observation).filter_by(video_id=video.id).delete(synchronize_session=False)
    session.delete(video)
    session.commit()


def set_channel_language(session: Session, identity: AuthIdentity, channel_id: int, language: str) -> dict[str, object]:
    require_admin(identity)
    if channel_id <= 0:
        raise ValueError("channel_id must be positive")
    normalized = language.strip()
    if not normalized or len(normalized) > 100:
        raise ValueError("language is required")
    channel = session.get(Channel, channel_id)
    if channel is None:
        raise LookupError("channel not found")
    override = session.query(ChannelLanguageOverride).filter_by(channel_id=channel_id).one_or_none()
    if override is None:
        override = ChannelLanguageOverride(channel_id=channel_id, language=normalized)
        session.add(override)
    else:
        override.language = normalized
        override.updated_at = datetime.now(UTC)
    channel.language = normalized
    session.commit()
    return {"channel_id": channel.id, "channel_name": channel.name, "language": normalized, "overridden": True}
