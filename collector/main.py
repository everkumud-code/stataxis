"""CLI entry point for STAXIS YouTube collection passes."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from collector.storage import create_database, save_observations
from collector.youtube.client import YouTubeClient
from collector.youtube.collector import ChannelTarget, collect_channel


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("stx-collector")


def load_targets(path: Path) -> list[ChannelTarget]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [ChannelTarget(**item) for item in payload["channels"]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a STAXIS YouTube collection pass")
    parser.add_argument("--channels", type=Path, default=Path("config/channels.json"))
    parser.add_argument("--max-videos", type=int, default=25)
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is not configured")

    engine = create_database(database_url)
    targets = load_targets(args.channels)

    with YouTubeClient() as client, Session(engine) as session:
        for target in targets:
            observations = collect_channel(client, target, args.max_videos)
            saved = save_observations(
                session=session,
                channel_name=target.name,
                channel_youtube_id=target.channel_id,
                network=target.network,
                language=target.language,
                observations=observations,
            )
            logger.info(
                "%s: collected=%d saved=%d observations",
                target.name,
                len(observations),
                saved,
            )
            for observation in observations:
                logger.info(
                    "%s | views=%s | live=%s | concurrent=%s",
                    observation.title,
                    observation.view_count,
                    observation.is_live,
                    observation.concurrent_viewers,
                )


if __name__ == "__main__":
    main()
