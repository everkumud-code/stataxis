"""CLI entry point for STAXIS YouTube collection passes."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from collector.run import run_collection_pass
from collector.storage import create_database
from collector.youtube.client import YouTubeClient
from collector.youtube.collector import ChannelTarget

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("stx-collector")


def load_targets(path: Path) -> list[ChannelTarget]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [ChannelTarget(**item) for item in payload["channels"]]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a STAXIS YouTube collection pass"
    )
    parser.add_argument(
        "--channels",
        type=Path,
        default=Path("config/channels.json"),
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=25,
    )
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is not configured")

    engine = create_database(database_url)
    targets = load_targets(PROJECT_ROOT / args.channels)

    with YouTubeClient() as client, Session(engine) as session:
        result = run_collection_pass(
            session,
            client,
            targets,
            max_videos=args.max_videos,
        )
        logger.info(
            "collection run %d: videos=%d intelligence_videos=%d snapshots=%d errors=%d",
            result.run_id,
            result.videos_observed,
            result.intelligence.videos_processed,
            result.intelligence.snapshots_built,
            result.intelligence.errors,
        )


if __name__ == "__main__":
    main()
