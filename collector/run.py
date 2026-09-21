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


def _describe_skipped(skipped: dict[str, str]) -> str:
    return ", ".join(f"{channel_id} ({reason})" for channel_id, reason in sorted(skipped.items()))[:1500]


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

    pass_started_at = datetime.now(UTC)
    run = CollectionRun(
        started_at=pass_started_at,
        status="running",
        channels_attempted=len(targets),
        videos_observed=0,
    )
    session.add(run)
    session.commit()

    videos_observed = 0
    try:
        skipped: dict[str, str] = {}
        collections = collect_channels_batched(client, targets, max_videos, skipped=skipped)
        if targets and not collections:
            raise RuntimeError(f"no channel could be collected: {_describe_skipped(skipped)}")
        for target in targets:
            collection = collections.get(target.channel_id)
            if collection is None:
                continue
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

        intelligence = process_persisted_observations(session, since=pass_started_at)
        run = session.get(CollectionRun, run.id)
        if run is None:  # pragma: no cover - impossible while session is active
            raise RuntimeError("collection run disappeared during processing")
        run.finished_at = datetime.now(UTC)
        run.videos_observed = videos_observed
        problems = []
        if skipped:
            problems.append(f"channels skipped: {_describe_skipped(skipped)}")
        if intelligence.errors:
            problems.append(f"intelligence errors: {intelligence.errors}")
        run.status = "partial" if problems else "success"
        run.error_message = "; ".join(problems)[:2000] if problems else None
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
