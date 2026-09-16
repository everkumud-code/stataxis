"""Authenticated manual YouTube evaluation service for commercial StatAxis V1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from api.access import VideoAccessPolicy, require_capability
from api.auth import AuthIdentity
from collector.storage import Channel, Video
from collector.storage import save_observations
from collector.youtube.client import YouTubeClient
from collector.youtube.manual_live import ManualLiveTarget, fetch_manual_live
from metrics.persistence import persist_video_intelligence


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
            "available_signals": self.available_signals,
            "data": self.data,
            "analysis": self.analysis,
            "view": self.view,
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
    from api.auth_service import policy_for_identity

    policy: VideoAccessPolicy = policy_for_identity(identity)
    require_capability(policy, "can_evaluate")
    target = ManualLiveTarget.from_url(url, display_name)
    owns_client = client is None
    youtube = client or YouTubeClient()
    try:
        channel_meta = youtube.get_channel(fetch_manual_live(youtube, target).channel_id)
        observation = fetch_manual_live(youtube, target)
        channel_snippet = channel_meta.get("snippet", {})
        channel_name = str(channel_snippet.get("title") or observation.channel_id)
        channel_network = str(channel_snippet.get("customUrl") or "unknown")
        language = str(channel_snippet.get("defaultLanguage") or "unknown")
        saved = save_observations(
            session,
            channel_name=channel_name,
            channel_youtube_id=observation.channel_id,
            network=channel_network,
            language=language,
            observations=[observation],
        )
        video = session.query(Video).filter_by(youtube_video_id=observation.video_id).one()
        channel = session.query(Channel).filter_by(id=video.channel_id).one()
        count = session.query(Video).join(Channel).filter(Video.id == video.id).count()
        observation_count = session.query(__import__("collector.storage", fromlist=["Observation"]).Observation).filter_by(video_id=video.id).count()
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
                available_signals=0,
                data=[observation.title],
                analysis=["A baseline is not yet established. A second observation is required for change-based intelligence."],
                view="Signal captured. STX Index is withheld until a valid comparison window exists.",
            )
        record = persist_video_intelligence(session, video.id)
        payload = __import__("json").loads(record.view_json)
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
            available_signals=record.available_signals,
            data=list(payload.get("data", [])),
            analysis=list(payload.get("analysis", [])),
            view=str(payload.get("view", "")),
        )
    finally:
        if owns_client:
            youtube.close()
