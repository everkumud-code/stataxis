"""Authenticated manual YouTube evaluation service for commercial StatAxis V1."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from api.access import require_capability
from api.auth import AuthIdentity
from api.auth_service import policy_for_identity
from collector.storage import Channel, Observation, Video, save_observations
from collector.youtube.client import YouTubeClient
from collector.youtube.manual_live import ManualLiveTarget, fetch_manual_live
from metrics.persistence import persist_video_intelligence
from metrics.stx_index import stx_display


@dataclass(frozen=True)
class EvaluationResult:
    """Stable response contract for one manual URL evaluation."""

    video_id: int
    youtube_video_id: str
    display_name: str
    channel_id: int
    channel_name: str
    observation_saved: bool
    observation_count: int
    stx_index: float | None
    confidence: float
    available_signals: int
    data: list[str]
    analysis: list[str]
    view: str
    display_stx_index: float | None = None
    preliminary: bool = True
    details: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "video_id": self.video_id,
            "youtube_video_id": self.youtube_video_id,
            "display_name": self.display_name,
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "observation_saved": self.observation_saved,
            "observation_count": self.observation_count,
            "stx_index": self.stx_index,
            "confidence": self.confidence,
            "display_stx_index": self.display_stx_index,
            "preliminary": self.preliminary,
            "available_signals": self.available_signals,
            "data": self.data,
            "analysis": self.analysis,
            "view": self.view,
            "details": self.details,
        }


def _aware(value):
    """A stored or API timestamp as an aware datetime (ISO text from YouTube, or a datetime from the database); None when absent or unreadable."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _iso(value):
    value = _aware(value)
    return value.isoformat() if value else None


def _number(value):
    try:
        return None if value in (None, "") else int(value)
    except (TypeError, ValueError):
        return None


def video_details(session: Session, video: Video, channel: Channel, channel_meta: dict) -> dict[str, object]:
    """What was measured about this video and its channel, straight from the stored observations and the channel record: views, likes, comments, when it was uploaded or went live, and how it moved since the last look.
    Nothing here is estimated; a figure YouTube did not give (hidden likes, no live audience) stays None so the screen shows a dash."""
    rows = session.query(Observation).filter_by(video_id=video.id).order_by(Observation.observed_at).all()
    now = rows[-1] if rows else None
    before = rows[-2] if len(rows) > 1 else None
    published = _aware(video.published_at)
    started, ended = _aware(video.live_started_at), _aware(video.live_ended_at)
    clock = datetime.now(UTC)
    views, likes, comments = (now.view_count, now.like_count, now.comment_count) if now else (None, None, None)
    live_minutes = None
    if started:
        live_minutes = max(0, round(((ended or clock) - started).total_seconds() / 60))
    concurrent = [r.concurrent_viewers for r in rows if r.concurrent_viewers is not None]
    since = None
    if now and before:
        gap = (_aware(now.observed_at) - _aware(before.observed_at)).total_seconds() / 3600
        gain = lambda a, b: None if a is None or b is None else a - b
        views_gained = gain(now.view_count, before.view_count)
        since = {
            "from": _iso(before.observed_at),
            "hours": round(gap, 2),
            "views_gained": views_gained,
            "likes_gained": gain(now.like_count, before.like_count),
            "comments_gained": gain(now.comment_count, before.comment_count),
            "views_per_hour": round(views_gained / gap, 1) if views_gained is not None and gap > 0 else None,
        }
    stats = channel_meta.get("statistics", {}) or {}
    snippet = channel_meta.get("snippet", {}) or {}
    return {
        "youtube_url": f"https://www.youtube.com/watch?v={video.youtube_video_id}",
        "thumbnail_url": video.thumbnail_url,
        "status": (now.classification if now else "UNKNOWN"),
        "is_live": bool(now and now.is_live),
        "uploaded_at": _iso(published),
        "age_hours": round((clock - published).total_seconds() / 3600, 1) if published else None,
        "live_started_at": _iso(started),
        "live_ended_at": _iso(ended),
        "live_minutes": live_minutes,
        "views": views,
        "likes": likes,
        "comments": comments,
        "likes_per_100_views": round(likes * 100 / views, 2) if likes is not None and views else None,
        "comments_per_1000_views": round(comments * 1000 / views, 2) if comments is not None and views else None,
        "views_per_hour_since_upload": round(views / ((clock - published).total_seconds() / 3600), 1) if views is not None and published and clock > published else None,
        "concurrent_now": now.concurrent_viewers if now else None,
        "concurrent_peak": max(concurrent) if concurrent else None,
        "concurrent_average": round(sum(concurrent) / len(concurrent)) if concurrent else None,
        "first_observed_at": _iso(rows[0].observed_at) if rows else None,
        "last_observed_at": _iso(now.observed_at) if now else None,
        "since_previous": since,
        "channel": {
            "name": channel.name,
            "handle": snippet.get("customUrl"),
            "url": f"https://www.youtube.com/channel/{channel.youtube_channel_id}" if getattr(channel, "youtube_channel_id", None) else None,
            "created_at": snippet.get("publishedAt"),
            "country": snippet.get("country"),
            "subscribers": None if stats.get("hiddenSubscriberCount") else _number(stats.get("subscriberCount")),
            "total_views": _number(stats.get("viewCount")),
            "video_count": _number(stats.get("videoCount")),
        },
    }


def evaluate_youtube_url(
    session: Session,
    identity: AuthIdentity,
    url: str,
    display_name: str,
    *,
    client: YouTubeClient | None = None,
) -> EvaluationResult:
    """Fetch, persist, and measure one manually supplied YouTube URL."""
    require_capability(policy_for_identity(identity), "can_evaluate_url")
    target = ManualLiveTarget.from_url(url, display_name)
    owns_client = client is None
    youtube = client or YouTubeClient()
    try:
        observation = fetch_manual_live(youtube, target)
        channel_meta = youtube.get_channel(observation.channel_id)
        snippet = channel_meta.get("snippet", {})
        channel_name = str(snippet.get("title") or observation.channel_id)
        network = str(snippet.get("customUrl") or "unknown")
        language = str(snippet.get("defaultLanguage") or "unknown")
        saved = save_observations(
            session,
            channel_name=channel_name,
            channel_youtube_id=observation.channel_id,
            network=network,
            language=language,
            observations=[observation],
        )
        video = session.query(Video).filter_by(youtube_video_id=observation.video_id).one()
        channel = session.query(Channel).filter_by(id=video.channel_id).one()
        observation_count = session.query(Observation).filter_by(video_id=video.id).count()
        if observation_count < 2:
            return EvaluationResult(
                video_id=video.id,
                youtube_video_id=video.youtube_video_id,
                display_name=observation.title,
                channel_id=channel.id,
                channel_name=channel.name,
                observation_saved=bool(saved),
                observation_count=observation_count,
                stx_index=None,
                confidence=0.0,
                display_stx_index=None,
                preliminary=True,
                available_signals=0,
                details=video_details(session, video, channel, channel_meta),
                data=[observation.title],
                analysis=["A baseline is not yet established. A second observation is required for change-based intelligence."],
                view="Signal captured. STX Index is withheld until a valid comparison window exists.",
            )
        record = persist_video_intelligence(session, video.id)
        payload = json.loads(record.view_json)
        return EvaluationResult(
            video_id=video.id,
            youtube_video_id=video.youtube_video_id,
            display_name=observation.title,
            channel_id=channel.id,
            channel_name=channel.name,
            observation_saved=bool(saved),
            observation_count=observation_count,
            stx_index=record.score,
            confidence=record.confidence,
            display_stx_index=stx_display(record.score, record.confidence)["display_score"],
            preliminary=bool(stx_display(record.score, record.confidence)["preliminary"]),
            available_signals=record.available_signals,
            data=list(payload.get("data", [])),
            analysis=list(payload.get("analysis", [])),
            view=str(payload.get("view", "")),
            details=video_details(session, video, channel, channel_meta),
        )
    finally:
        if owns_client:
            youtube.close()
