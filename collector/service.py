"""Always-on collection and live polling service."""

from __future__ import annotations

import logging
import os
import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Callable

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from collector.main import load_targets
from collector.run import run_collection_pass
from collector.run_once import _sanitize_error_message
from collector.storage import Channel, Observation, Video, create_database, save_observations
from collector.youtube.client import YouTubeAPIError, YouTubeClient
from collector.youtube.collector import normalize_video
from collector.youtube.quota import env_non_negative_int

ROOT = Path(__file__).resolve().parents[1]
LIVE_WINDOW = timedelta(minutes=20)
LIVE_BATCH_SIZE = 50
logger = logging.getLogger("stataxis-service")


@dataclass(frozen=True)
class LivePollResult:
    candidates: int
    batches: int
    observations_saved: int
    ended: int
    errors: int


def interval_seconds(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        raw = str(default)
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum} seconds")
    return value


def quota_backoff_seconds(attempt: int) -> int:
    return min(300, 30 * (2 ** max(0, attempt - 1)))


def _live_candidates(session: Session, now: datetime) -> list[tuple[Observation, Video, Channel]]:
    cutoff = now - LIVE_WINDOW
    latest = (
        select(
            Observation.video_id.label("video_id"),
            func.max(Observation.observed_at).label("latest_observed_at"),
        )
        .group_by(Observation.video_id)
        .subquery()
    )
    stmt = (
        select(Observation, Video, Channel)
        .join(latest, and_(
            latest.c.video_id == Observation.video_id,
            latest.c.latest_observed_at == Observation.observed_at,
        ))
        .join(Video, Video.id == Observation.video_id)
        .join(Channel, Channel.id == Observation.channel_id)
        .where(
            Observation.is_live.is_(True),
            Observation.observed_at >= cutoff,
            Channel.active.is_(True),
        )
        .order_by(Observation.observed_at.asc(), Observation.id.asc())
    )
    return list(session.execute(stmt).all())


def _chunks(items: list[str], size: int = LIVE_BATCH_SIZE):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def poll_live_once(
    session: Session,
    client: YouTubeClient,
    *,
    now: datetime | None = None,
) -> LivePollResult:
    """Poll the currently-live database universe in YouTube's 50-ID batches."""
    observed_at = now or datetime.now(UTC)
    candidates = _live_candidates(session, observed_at)
    batches = list(_chunks([video.youtube_video_id for _, video, _ in candidates]))
    candidate_by_id = {video.youtube_video_id: (observation, video, channel) for observation, video, channel in candidates}

    saved = 0
    ended = 0
    errors = 0
    for batch in batches:
        try:
            items = client.get_live_videos(batch)
        except YouTubeAPIError as exc:
            if exc.status_code in {403, 429}:
                raise
            errors += 1
            continue
        except Exception:
            errors += 1
            continue

        for item in items:
            video_id = str(item.get("id", ""))
            candidate = candidate_by_id.get(video_id)
            if candidate is None:
                continue
            _, video, channel = candidate
            payload = dict(item)
            payload.setdefault("snippet", {
                "title": video.title,
                "publishedAt": video.published_at,
            })
            observation = normalize_video(
                payload,
                channel.youtube_channel_id,
                observed_at,
            )
            try:
                saved += save_observations(
                    session=session,
                    channel_name=channel.name,
                    channel_youtube_id=channel.youtube_channel_id,
                    network=channel.network,
                    language=channel.language,
                    region=channel.region,
                    observations=[observation],
                )
            except Exception:
                session.rollback()
                errors += 1
                continue
            if not observation.is_live:
                ended += 1

    return LivePollResult(len(candidates), len(batches), saved, ended, errors)


def install_signal_handlers(stop_event: Event) -> None:
    def stop(*_: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


def _log_loop_error(loop: str, exc: Exception, secrets: tuple[str | None, ...]) -> None:
    message = _sanitize_error_message(str(exc), secrets)
    logger.error("%s loop failed: %s: %s", loop, type(exc).__name__, message)


def _collection_loop(
    engine,
    client: YouTubeClient,
    stop: Event,
    collect_seconds: int,
    secrets: tuple[str | None, ...],
) -> None:
    """Full collection on its own schedule. Never raises."""
    next_collect = time.monotonic()
    quota_attempt = 0
    while not stop.is_set():
        now = time.monotonic()
        if now >= next_collect:
            try:
                with Session(engine) as session:
                    targets = load_targets(ROOT / "config/channels.json")
                    result = run_collection_pass(session, client, targets)
                logger.info(
                    "collection counts channels=%d videos=%d snapshots=%d errors=%d",
                    len(targets),
                    result.videos_observed,
                    result.intelligence.snapshots_built,
                    result.intelligence.errors,
                )
                quota_attempt = 0
                next_collect = now + collect_seconds
            except YouTubeAPIError as exc:
                quota_attempt += 1
                delay = quota_backoff_seconds(quota_attempt) if exc.status_code in {403, 429} else collect_seconds
                _log_loop_error("collection", exc, secrets)
                logger.info("collection counts channels=0 videos=0 snapshots=0 errors=1")
                next_collect = now + delay
            except Exception as exc:
                _log_loop_error("collection", exc, secrets)
                logger.info("collection counts channels=0 videos=0 snapshots=0 errors=1")
                next_collect = now + collect_seconds
        stop.wait(min(max(0.0, next_collect - time.monotonic()), 1.0))


def _live_loop(
    engine,
    client: YouTubeClient,
    stop: Event,
    live_poll_seconds: int,
    secrets: tuple[str | None, ...],
) -> None:
    """Live viewer polling on its own schedule. Never raises."""
    next_live = time.monotonic()
    quota_attempt = 0
    while not stop.is_set():
        now = time.monotonic()
        if now >= next_live:
            try:
                with Session(engine) as session:
                    result = poll_live_once(session, client, now=datetime.now(UTC))
                logger.info(
                    "live poll counts candidates=%d batches=%d saved=%d ended=%d errors=%d",
                    result.candidates,
                    result.batches,
                    result.observations_saved,
                    result.ended,
                    result.errors,
                )
                quota_attempt = 0
                next_live = now + live_poll_seconds
            except YouTubeAPIError as exc:
                quota_attempt += 1
                delay = quota_backoff_seconds(quota_attempt) if exc.status_code in {403, 429} else live_poll_seconds
                _log_loop_error("live", exc, secrets)
                logger.info("live poll counts candidates=0 batches=0 saved=0 ended=0 errors=1")
                next_live = now + delay
            except Exception as exc:
                _log_loop_error("live", exc, secrets)
                logger.info("live poll counts candidates=0 batches=0 saved=0 ended=0 errors=1")
                next_live = now + live_poll_seconds
        stop.wait(min(max(0.0, next_live - time.monotonic()), 1.0))


def run_service(
    database_url: str,
    *,
    client_factory: Callable[[], YouTubeClient] = YouTubeClient,
    stop_event: Event | None = None,
) -> None:
    """Run full collection and live polling as two independent loops.

    Collection runs in its own thread so a long pass (many channels) never delays
    live polling. Each loop has its own HTTP client. They share one process-wide
    request budget, and STAXIS_YOUTUBE_LIVE_RESERVE_PER_MINUTE keeps part of the
    per-minute budget free for live polling.
    """
    collect_seconds = interval_seconds("COLLECT_SECONDS", 600, 60)
    live_poll_seconds = interval_seconds("LIVE_POLL_SECONDS", 30, 5)
    live_reserve = env_non_negative_int("STAXIS_YOUTUBE_LIVE_RESERVE_PER_MINUTE", 0)
    engine = create_database(database_url)
    stop = stop_event or Event()
    install_signal_handlers(stop)
    secrets = (database_url, os.getenv("YOUTUBE_API_KEY"))

    with client_factory() as collect_client, client_factory() as live_client:
        collect_client.reserve_per_minute = live_reserve
        collector = Thread(
            target=_collection_loop,
            args=(engine, collect_client, stop, collect_seconds, secrets),
            name="collection-loop",
            daemon=True,
        )
        collector.start()
        try:
            _live_loop(engine, live_client, stop, live_poll_seconds, secrets)
        finally:
            stop.set()
            collector.join(timeout=30)

    logger.info("service stopped counts collection=1 live_poll=1")


def main() -> int:
    database_url = os.getenv("DATABASE_URL")
    if not database_url or not database_url.strip():
        raise ValueError("DATABASE_URL is not configured")
    run_service(database_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
