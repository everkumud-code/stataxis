"""One production collection pass with durable run lifecycle tracking."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from collector.intelligence import IntelligenceRunResult, process_persisted_observations
from collector.retention import run_retention_if_due
from collector.storage import CollectionRun, save_observations
from collector.youtube.client import YouTubeClient
from collector.youtube.collector import ChannelTarget, collect_channels_batched

logger = logging.getLogger("stx-collector")

# Quota / rate-limit errors affect every channel: stop the pass so the caller can back off.
_PASS_FATAL_STATUS = {403, 429}


@dataclass(frozen=True)
class CollectionPassResult:
    """Operational result for one collection + intelligence pass."""

    run_id: int
    videos_observed: int
    intelligence: IntelligenceRunResult
    channel_errors: int = 0


def _describe_skipped(skipped: dict[str, str], names: dict[str, str] | None = None) -> str:
    names = names or {}
    return ", ".join(
        f"{names.get(channel_id, channel_id)} [{channel_id}: {reason}]" for channel_id, reason in sorted(skipped.items())
    )[:1500]


def run_collection_pass(
    session: Session,
    client: YouTubeClient,
    targets: list[ChannelTarget],
    *,
    max_videos: int = 25,
    intelligence: bool = True,
) -> CollectionPassResult:
    """Collect, persist, score, and durably record one production pass.

    Channels are fetched in batches (far fewer API units). One bad channel never stops
    the rest: it is skipped, counted and reported, and the pass ends as ``partial``.
    Quota errors (403/429) abort the pass so the caller can back off. The pass fails
    only when no channel could be collected at all.
    """
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
    channel_errors = 0
    failed_channels: list[str] = []
    last_error: Exception | None = None
    try:
        skipped: dict[str, str] = {}
        names = {target.channel_id: target.name for target in targets}
        collections = collect_channels_batched(client, targets, max_videos, skipped=skipped)
        channel_errors += len(skipped)
        failed_channels.extend(sorted(skipped))
        if targets and not collections:
            raise RuntimeError(f"no channel could be collected: {_describe_skipped(skipped, names)}")
        for target in targets:
            collection = collections.get(target.channel_id)
            if collection is None:
                continue
            observations = collection.observations
            try:
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
                    segment=target.segment,
                    channel_stats=(
                        collection.observed_at,
                        collection.subscribers,
                        collection.total_views,
                        collection.video_count,
                    ),
                )
            except Exception as exc:  # one bad channel must not stop the rest of the universe
                session.rollback()
                channel_errors += 1
                last_error = exc
                failed_channels.append(target.name)
                logger.error("channel %s (%s) skipped: %s", target.name, target.channel_id, type(exc).__name__)
                continue
            videos_observed += len({item.video_id for item in observations})
            if saved < 0:  # pragma: no cover - defensive invariant guard
                raise RuntimeError("collector returned a negative save count")

        if targets and channel_errors >= len(targets) and last_error is not None:
            raise last_error  # every channel failed: the pass itself is broken

        # Score only the videos observed in this pass: unchanged videos would produce identical snapshots.
        intelligence_result = (
            process_persisted_observations(session, since=pass_started_at)
            if intelligence
            else IntelligenceRunResult(0, 0, 0)
        )
        run = session.get(CollectionRun, run.id)
        if run is None:  # pragma: no cover - impossible while session is active
            raise RuntimeError("collection run disappeared during processing")
        run.finished_at = datetime.now(UTC)
        run.videos_observed = videos_observed
        problems = []
        if skipped:
            problems.append(f"channels skipped: {_describe_skipped(skipped, names)}")
        other_failed = channel_errors - len(skipped)
        if other_failed:
            problems.append(f"channels failed while saving: {other_failed}")
        if intelligence_result.errors:
            problems.append(f"intelligence errors: {intelligence_result.errors}")
        run.status = "partial" if problems else "success"
        run.error_message = "; ".join(problems)[:2000] if problems else None
        session.commit()
        run_id = run.id
        # Enforce YouTube API data retention. Never raises and never fails a collection pass.
        run_retention_if_due(session)
        return CollectionPassResult(run_id, videos_observed, intelligence_result, channel_errors)
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
