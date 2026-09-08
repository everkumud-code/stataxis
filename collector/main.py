"""CLI entry point for the first STAXIS collection smoke test."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from collector.youtube.client import YouTubeClient
from collector.youtube.collector import ChannelTarget, collect_channel


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

    targets = load_targets(args.channels)
    with YouTubeClient() as client:
        for target in targets:
            observations = collect_channel(client, target, args.max_videos)
            logger.info("%s: collected %d observations", target.name, len(observations))
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
