"""Build channel rankings from persisted STAXIS observations."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from collector.storage import Channel, Observation, Video
from metrics.eligibility import (
    eligible_for_live_concurrent,
    eligible_for_vod_views,
)
from metrics.ranking import (
    ChannelSnapshot,
    build_snapshot,
    rank_channels,
    rank_channels_by_live,
)


def latest_observations_by_video(session: Session) -> list[Observation]:
    """Return the newest observation for every stored video."""
    latest = (
        select(
            Observation.video_id,
            func.max(Observation.observed_at).label("latest_at"),
        )
        .group_by(Observation.video_id)
        .subquery()
    )

    stmt = select(Observation).join(
        latest,
        (Observation.video_id == latest.c.video_id)
        & (Observation.observed_at == latest.c.latest_at),
    )

    return list(session.scalars(stmt).all())


def _build_current_snapshots(session: Session) -> list[ChannelSnapshot]:
    """Build eligible current channel snapshots without choosing a ranking mode."""
    observations = latest_observations_by_video(session)

    if not observations:
        return []

    channels = {
        channel.id: channel
        for channel in session.scalars(select(Channel)).all()
    }

    videos = {
        video.id: video
        for video in session.scalars(select(Video)).all()
    }

    grouped: dict[int, dict[str, list[int | None]]] = {}

    for observation in observations:
        video = videos.get(observation.video_id)

        if video is None:
            continue

        bucket = grouped.setdefault(
            video.channel_id,
            {
                "views": [],
                "concurrent": [],
            },
        )

        if eligible_for_vod_views(observation.classification):
            bucket["views"].append(observation.view_count)

        if eligible_for_live_concurrent(observation.classification):
            bucket["concurrent"].append(observation.concurrent_viewers)

    snapshots: list[ChannelSnapshot] = []

    for channel_id, values in grouped.items():
        channel = channels.get(channel_id)

        if channel is None:
            continue

        snapshots.append(
            build_snapshot(
                channel_id=channel.youtube_channel_id,
                name=channel.name,
                language=channel.language,
                view_counts=values["views"],
                concurrent_counts=values["concurrent"],
            )
        )

    return snapshots


def build_current_channel_rankings(session: Session) -> list[ChannelSnapshot]:
    """Build the current VOD-view ranking from eligible observations.

    This is deliberately a current snapshot, not yet a historical STX score.
    """
    return rank_channels(_build_current_snapshots(session))


def build_current_live_channel_rankings(session: Session) -> list[ChannelSnapshot]:
    """Build the current live-audience ranking from eligible observations."""
    return rank_channels_by_live(_build_current_snapshots(session))
