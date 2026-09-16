"""One production collection pass with durable run lifecycle tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from collector.intelligence import IntelligenceRunResult, process_persisted_observations
from collector.storage import CollectionRun, save_observations
from collector.youtube.collector import ChannelTarget, collect_channel
from collector.youtube.client import YouTubeClient


@dataclass(frozen=True)
class CollectionPassResult:
    """Operational result for one collection + intelligence pass."""

    run_id: int
    videos_observed: int
    intelligence: IntelligenceRunResult


def run_collection_pass(session: Session, client: YouTubeClient, targets: list[ChannelTarget], *, max_videos: int = 25) -> CollectionPassResult:
    """Collect every reachable channel, persist successful observations, then score them."""
    if max_videos <= 0:
        raise ValueError("max_videos must be positive")
    run = CollectionRun(started_at=datetime.now(UTC), status="running", channels_attempted=len(targets), videos_observed=0)
    session.add(run)
    session.commit()
    videos_observed = 0
    channel_errors: list[str] = []
    try:
        for target in targets:
            try:
                observations = collect_channel(client, target, max_videos)
                save_observations(session, target.name, target.channel_id, target.network, target.language, observations)
                videos_observed += len({item.video_id for item in observations})
            except Exception as exc:
                session.rollback()
                channel_errors.append(f"{target.name}: {str(exc)[:400]}")
                continue
        intelligence = process_persisted_observations(session)
        run = session.get(CollectionRun, run.id)
        if run is None:
            raise RuntimeError("collection run disappeared during processing")
        run.finished_at = datetime.now(UTC)
        run.videos_observed = videos_observed
        errors = channel_errors + ([f"intelligence errors: {intelligence.errors}"] if intelligence.errors else [])
        run.status = "partial" if errors else "success"
        run.error_message = " | ".join(errors)[:2000] if errors else None
        session.commit()
        return CollectionPassResult(run.id, videos_observed, intelligence)
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
