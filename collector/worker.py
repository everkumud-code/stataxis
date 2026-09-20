"""Long-running StatAxis production collection worker."""

from __future__ import annotations

import json
import logging
import os
import signal
import time
from pathlib import Path

from sqlalchemy.orm import Session

from collector.run import run_collection_pass
from collector.storage import Channel, create_database
from collector.youtube.client import YouTubeClient
from collector.youtube.collector import ChannelTarget

ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger("stataxis-worker")
_STOP = False


def _stop(*_: object) -> None:
    global _STOP
    _STOP = True


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw.strip())


def load_targets(session: Session) -> list[ChannelTarget]:
    """Build the active monitoring universe from persisted channels plus config."""
    path = ROOT / "config" / "channels.json"
    configured = json.loads(path.read_text(encoding="utf-8")).get("channels", [])
    existing = {
        row.youtube_channel_id: row
        for row in session.query(Channel).filter(Channel.active.is_(True)).all()
    }
    targets: list[ChannelTarget] = []
    for item in configured:
        row = existing.get(item["channel_id"])
        targets.append(ChannelTarget(
            channel_id=item["channel_id"],
            name=row.name if row else item["name"],
            language=row.language if row else item.get("language", "unknown"),
            network=row.network if row else item.get("network", "unknown"),
            segment=(row.segment if row else item.get("segment", "news")) or "news",
        ))
    configured_ids = {item["channel_id"] for item in configured}
    for row in existing.values():
        if row.youtube_channel_id not in configured_ids:
            targets.append(ChannelTarget(
                channel_id=row.youtube_channel_id,
                name=row.name,
                language=row.language,
                network=row.network,
                segment=row.segment or "news",
            ))
    logger.info(
        "monitoring universe: configured=%d persisted_active=%d total=%d",
        len(configured),
        len(existing),
        len(targets),
    )
    return targets


def run_worker() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url or not database_url.strip():
        raise ValueError("DATABASE_URL is not configured")
    interval = max(30, _env_int("STAXIS_COLLECTION_INTERVAL_SECONDS", 300))
    max_videos = max(1, _env_int("STAXIS_COLLECTION_MAX_VIDEOS", 25))
    engine = create_database(database_url)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while not _STOP:
        started = time.monotonic()
        try:
            with Session(engine) as session, YouTubeClient() as client:
                targets = load_targets(session)
                if not targets:
                    logger.warning("no active channels configured")
                else:
                    result = run_collection_pass(
                        session, client, targets, max_videos=max_videos
                    )
                    logger.info(
                        "run=%d channels=%d videos=%d snapshots=%d errors=%d",
                        result.run_id,
                        len(targets),
                        result.videos_observed,
                        result.intelligence.snapshots_built,
                        result.intelligence.errors,
                    )
        except Exception:
            logger.exception("collection cycle failed")
        elapsed = time.monotonic() - started
        if not _STOP:
            time.sleep(max(0, interval - elapsed))


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("STX_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    run_worker()
