"""One production collection pass with durable run lifecycle tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from collector.intelligence import IntelligenceRunResult, process_persisted_observations
from collector.retention import run_retention_if_due
from collector.storage import CollectionRun, save_observations
from collector.youtube.collector import ChannelTarget, collect_channels_batched
from collector.youtube.client import YouTubeClient


@dataclass(frozen=True)
class CollectionPassResult:
    """Operational result for one collection + intelligence pass."""

    run_id: int
    videos_observed: int
    intelligence: IntelligenceRunResult


def run_collection_pass(
    session: Session,
    client: YouTubeClient,
    targets: list[ChannelTarget],
    *,
    max_videos: int = 25,
) -> CollectionPassResult:
    """Collect, persist, score, and durably record one production pass."""
    if max_videos <= 0:
        raise ValueError("max_videos must be positive")

    run = CollectionRun(
        started_at=datetime.now(UTC),
        status="running",
        channels_attempted=len(targets),
        videos_observed=0,
    )
    session.add(run)
    session.commit()

    videos_observed = 0
    try:
        collections = collect_channels_batched(client, targets, max_videos)
        for target in targets:
            collection = collections[target.channel_id]
            observations = collection.observations
            saved = save_observations(
                session=session,
                channel_name=target.name,
                channel_youtube_id=target.channel_id,
                network=target.network,
                language=target.language,
                observations=observations,
                region=target.region,
                avatar_url=collection.avatar_url,
                handle=collection.handle,
                channel_stats=(
                    collection.observed_at,
                    collection.subscribers,
                    collection.total_views,
                    collection.video_count,
                ),
            )
            videos_observed += len({item.video_id for item in observations})
            if saved < 0:  # pragma: no cover - defensive invariant guard
                raise RuntimeError("collector returned a negative save count")

        intelligence = process_persisted_observations(session)
        run = session.get(CollectionRun, run.id)
        if run is None:  # pragma: no cover - impossible while session is active
            raise RuntimeError("collection run disappeared during processing")
        run.finished_at = datetime.now(UTC)
        run.videos_observed = videos_observed
        run.status = "partial" if intelligence.errors else "success"
        run.error_message = (
            f"intelligence errors: {intelligence.errors}"
            if intelligence.errors
            else None
        )
        session.commit()
        run_id = run.id
        # Enforce YouTube API data retention. Never raises and never fails a collection pass.
        run_retention_if_due(session)
        return CollectionPassResult(run_id, videos_observed, intelligence)
    except Exception as exc:
        session.rollback()
        failed = session.get(CollectionRun, run.id)
        if failed is not None:
            failed.finished_at = datetime.now(UTC)
            failed.videos_observed = videos_observed
            failed.status = "failed"
            failed.error_message = str(exc)[:2000]
            session.commit()
        raise
