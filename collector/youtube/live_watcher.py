"""Continuous polling and persistence for manually supplied YouTube live streams."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from sqlalchemy.orm import Session

from collector.storage import save_observations
from collector.youtube.client import YouTubeClient
from collector.youtube.manual_live import ManualLiveTarget, fetch_manual_live

logger = logging.getLogger("stx-live-watcher")


def run_manual_live_watch(
    client: YouTubeClient,
    session: Session,
    target: ManualLiveTarget,
    *,
    interval_seconds: int = 30,
    sleep: Callable[[float], None] = time.sleep,
    max_polls: int | None = None,
) -> int:
    """Poll a manual live target until it is no longer live or the loop is stopped.

    Every successful poll is appended as a timestamped observation. The final
    non-live observation is persisted as well, allowing downstream analytics to
    see the transition from live to ended. API errors are logged and retried
    without terminating the watcher.
    """
    if interval_seconds < 30:
        raise ValueError("interval_seconds must be at least 30 seconds")
    if max_polls is not None and max_polls < 1:
        raise ValueError("max_polls must be at least 1")

    polls = 0
    saved = 0

    while max_polls is None or polls < max_polls:
        polls += 1
        try:
            observation = fetch_manual_live(client, target)
            saved += save_observations(
                session,
                channel_name=target.display_name,
                channel_youtube_id=observation.channel_id,
                network="youtube",
                language="unknown",
                observations=[observation] ,
            )
            logger.info(
                "saved live observation video=%s live=%s concurrent=%s",
                observation.video_id,
                observation.is_live,
                observation.concurrent_viewers,
            )
            if not observation.is_live:
                logger.info("manual live target ended: %s", target.display_name)
                break
        except Exception:
            logger.exception("live observation failed; retrying target=%s", target.display_name)

        if max_polls is not None and polls >= max_polls:
            break
        sleep(interval_seconds)

    return saved
