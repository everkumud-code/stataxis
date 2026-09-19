"""Single-pass scheduled collector entry point."""

from __future__ import annotations

import logging

from collector.main import load_targets
from collector.run import run_collection_pass
from collector.storage import create_database
from collector.youtube.client import YouTubeClient
from sqlalchemy.orm import Session
import os
from pathlib import Path

logger = logging.getLogger("stx-collector-once")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    try:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL is not configured")
        api_key = os.getenv("YOUTUBE_API_KEY")
        if not api_key:
            raise ValueError("YOUTUBE_API_KEY is not configured")

        engine = create_database(database_url)
        targets = load_targets(PROJECT_ROOT / "config/channels.json")
        with YouTubeClient(api_key=api_key) as client, Session(engine) as session:
            result = run_collection_pass(session, client, targets)
        logger.info(
            "collection cycle complete: run_id=%d channels=%d videos=%d "
            "intelligence_videos=%d snapshots=%d errors=%d",
            result.run_id,
            len(targets),
            result.videos_observed,
            result.intelligence.videos_processed,
            result.intelligence.snapshots_built,
            result.intelligence.errors,
        )
        return 0
    except Exception as exc:
        logger.error("collection cycle failed: %s", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
