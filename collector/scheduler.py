"""Simple local scheduler for repeated STAXIS collection passes."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time

logger = logging.getLogger("stx-scheduler")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run repeated STAXIS collection passes")
    parser.add_argument("--interval", type=int, default=300, help="seconds between passes")
    parser.add_argument("--max-videos", type=int, default=25)
    parser.add_argument("--once", action="store_true", help="run one pass and exit")
    args = parser.parse_args()

    if args.interval < 30:
        raise ValueError("--interval must be at least 30 seconds")

    while True:
        started = time.monotonic()
        try:
            result = subprocess.run(
                [sys.executable, "-m", "collector.main", "--max-videos", str(args.max_videos)],
                check=False,
            )
            if result.returncode != 0:
                logger.error("collection pass exited with code %d", result.returncode)
            else:
                logger.info("collection pass completed successfully")
        except KeyboardInterrupt:
            logger.info("scheduler stopped")
            return
        except Exception:
            logger.exception("collection pass failed; scheduler will continue")

        if args.once:
            return

        elapsed = time.monotonic() - started
        sleep_for = max(0, args.interval - elapsed)
        logger.info("next collection pass in %d seconds", sleep_for)
        time.sleep(sleep_for)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
