"""Always-on StatAxis collection and live-audience worker."""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from collector.run import run_collection_pass
from collector.storage import Channel, Observation, Video, create_database, save_observations
from collector.youtube.client import YouTubeAPIError, YouTubeClient
from collector.youtube.collector import ChannelTarget, normalize_video

ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger("stx-collector-service")
COLLECT_SECONDS_DEFAULT = 600
LIVE_POLL_SECONDS_DEFAULT = 30
LIVE_WINDOW_MINUTES = 20
MAX_LIVE_BATCH = 50
MAX_QUOTA_BACKOFF = 300


def quota_backoff_seconds(attempt: int) -> int:
    return min(MAX_QUOTA_BACKOFF, max(30, 30 * (2 ** max(0, attempt - 1))))


def _bounded_interval(name: str, default: int, minimum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum} seconds")
    return value


def service_intervals() -> tuple[int, int]:
    return (
        _bounded_interval("COLLECT_SECONDS", COLLECT_SECONDS_DEFAULT, 60),
        _bounded_interval("LIVE_POLL_SECONDS", LIVE_POLL_SECONDS_DEFAULT, 30),
    )


def load_targets() -> list[ChannelTarget]:
    payload = json.loads((ROOT / "config" / "channels.json").read_text(encoding="utf-8"))
    return [ChannelTarget(**item) for item in payload["channels"]]


def _live_video_ids(session: Session, *, now: datetime | None = None) -> list[tuple[str, Channel]]:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(minutes=LIVE_WINDOW_MINUTES)
    latest = (
        select(
            Observation.video_id.label("video_id"),
            func.max(Observation.observed_at).label("latest_at"),
        )
        .group_by(Observation.video_id)
        .subquery()
    )
    rows = session.execute(
        select(Observation, Channel)
        .join(latest, (latest.c.video_id == Observation.video_id) & (latest.c.latest_at == Observation.observed_at))
        .join(Channel, Channel.id == Observation.channel_id)
        .where(
            Observation.is_live.is_(True),
            Observation.observed_at >= cutoff,
            Channel.active.is_(True),
        )
    ).all()
    videos = {
        video.id: video
        for video in session.query(Video).filter(
            Video.id.in_([observation.video_id for observation, _ in rows])
        ).all()
    }
    return [
        (videos[observation.video_id].youtube_video_id, channel)
        for observation, channel in rows
        if observation.video_id in videos
    ]


def poll_live_once(
    session: Session,
    client: YouTubeClient,
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Poll live candidates in batches of 50 and persist every returned observation."""
    now = now or datetime.now(UTC)
    candidates = _live_video_ids(session, now=now)
    fetched = 0
    saved = 0
    for offset in range(0, len(candidates), MAX_LIVE_BATCH):
        batch = candidates[offset : offset + MAX_LIVE_BATCH]
        videos = client.get_live_videos([video_id for video_id, _ in batch])
        channels = {channel.youtube_channel_id: channel for _, channel in batch}
        for video in videos:
            video_channel_id = str(video.get("snippet", {}).get("channelId") or "")
            channel = channels.get(video_channel_id)
            if channel is None:
                channel = next(
                    (item for video_id, item in batch if video_id == video.get("id")),
                    None,
                )
            if channel is None:
                continue
            observation = normalize_video(video, channel.youtube_channel_id, now)
            saved += save_observations(
                session,
                channel_name=channel.name,
                channel_youtube_id=channel.youtube_channel_id,
                network=channel.network,
                language=channel.language,
                region=channel.region,
                observations=[observation],
            )
            fetched += 1
    return fetched, saved


def _sleep_with_stop(stop_event: threading.Event, seconds: float) -> None:
    stop_event.wait(max(0.0, seconds))


def run_service(
    *,
    stop_event: threading.Event | None = None,
    max_cycles: int | None = None,
) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is not configured")
    collect_seconds, live_poll_seconds = service_intervals()
    stop_event = stop_event or threading.Event()
    engine = create_database(database_url)
    collect_due = time.monotonic()
    live_due = collect_due
    live_quota_backoff = 0
    collection_quota_backoff = 0
    live_failures = 0
    collection_failures = 0
    cycles = 0

    with YouTubeClient() as client:
        while not stop_event.is_set():
            now = time.monotonic()
            if now >= collect_due:
                try:
                    with Session(engine) as session:
                        targets = load_targets()
                        result = run_collection_pass(session, client, targets)
                    logger.info(
                        "collection counts: channels=%d videos=%d snapshots=%d errors=%d",
                        len(targets), result.videos_observed,
                        result.intelligence.snapshots_built, result.intelligence.errors,
                    )
                    collection_quota_backoff = 0
                    collection_failures = 0
                except YouTubeAPIError as exc:
                    collection_failures += 1
                    if exc.status_code in {403, 429}:
                        collection_quota_backoff = quota_backoff_seconds(collection_failures)
                    logger.info("collection counts: channels=0 videos=0 snapshots=0 errors=%d", collection_failures)
                except Exception:
                    collection_failures += 1
                    logger.info("collection counts: channels=0 videos=0 snapshots=0 errors=%d", collection_failures)
                collect_due = time.monotonic() + max(collect_seconds, collection_quota_backoff)

            if now >= live_due and not stop_event.is_set():
                try:
                    with Session(engine) as session:
                        fetched, saved = poll_live_once(session, client)
                    logger.info("live poll counts: videos=%d observations=%d", fetched, saved)
                    live_quota_backoff = 0
                    live_failures = 0
                except YouTubeAPIError as exc:
                    live_failures += 1
                    if exc.status_code in {403, 429}:
                        live_quota_backoff = quota_backoff_seconds(live_failures)
                    logger.info("live poll counts: videos=0 observations=0 errors=%d", live_failures)
                except Exception:
                    live_failures += 1
                    logger.info("live poll counts: videos=0 observations=0 errors=%d", live_failures)
                live_due = time.monotonic() + max(live_poll_seconds, live_quota_backoff)

            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                return
            wait = min(
                max(0.0, collect_due - time.monotonic()),
                max(0.0, live_due - time.monotonic()),
                1.0,
            )
            _sleep_with_stop(stop_event, wait)

def install_signal_handlers(stop_event: threading.Event) -> None:
    def stop(*_: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


def main() -> None:
    stop_event = threading.Event()
    install_signal_handlers(stop_event)
    logging.basicConfig(
        level=os.getenv("STX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        run_service(stop_event=stop_event)
    finally:
        logger.info("worker stopped cleanly")


if __name__ == "__main__":
    main()
