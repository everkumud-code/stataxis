"""One production collection pass with durable run lifecycle tracking."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from collector.intelligence import IntelligenceRunResult, process_persisted_observations
from collector.storage import CollectionRun, save_observations
from collector.youtube.collector import ChannelTarget, collect_channel_with_stats
from collector.youtube.client import YouTubeAPIError, YouTubeClient

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


def run_collection_pass(
    session: Session,
    client: YouTubeClient,
    targets: list[ChannelTarget],
    *,
    max_videos: int = 25,
    intelligence: bool = True,
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
    channel_errors = 0
    failed_channels: list[str] = []
    last_error: Exception | None = None
    try:
        for target in targets:
            try:
                collection = collect_channel_with_stats(client, target, max_videos)
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
                    segment=target.segment,
                    channel_stats=(
                        collection.observed_at,
                        collection.subscribers,
                        collection.total_views,
                        collection.video_count,
                    ),
                )
            except YouTubeAPIError as exc:
                if exc.status_code in _PASS_FATAL_STATUS:
                    raise
                session.rollback()
                channel_errors += 1
                last_error = exc
                failed_channels.append(target.name)
                logger.error("channel %s (%s) skipped: %s", target.name, target.channel_id, type(exc).__name__)
                continue
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

        if targets and channel_errors == len(targets) and last_error is not None:
            raise last_error  # every channel failed: the pass itself is broken

        # When a pass is split into slices only the last slice scores, so scoring runs once per pass.
        intelligence_result = process_persisted_observations(session) if intelligence else IntelligenceRunResult(0, 0, 0)
        run = session.get(CollectionRun, run.id)
        if run is None:  # pragma: no cover - impossible while session is active
            raise RuntimeError("collection run disappeared during processing")
        run.finished_at = datetime.now(UTC)
        run.videos_observed = videos_observed
        problems = []
        if channel_errors:
            problems.append(f"channels skipped: {channel_errors} ({', '.join(failed_channels[:10])})")
        if intelligence_result.errors:
            problems.append(f"intelligence errors: {intelligence_result.errors}")
        run.status = "partial" if problems else "success"
        run.error_message = "; ".join(problems)[:2000] if problems else None
        session.commit()
        return CollectionPassResult(run.id, videos_observed, intelligence_result, channel_errors)
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
