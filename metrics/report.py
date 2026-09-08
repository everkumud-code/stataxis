"""CLI for printing the current STAXIS channel ranking."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from collector.storage import create_database
from metrics.database_ranking import build_current_channel_rankings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is not configured")

    engine = create_database(database_url)
    with Session(engine) as session:
        rankings = build_current_channel_rankings(session)

    print("STAXIS CURRENT CHANNEL RANKING")
    print("=" * 72)
    if not rankings:
        print("No observations available yet.")
        return

    for position, item in enumerate(rankings, start=1):
        avg_concurrent = (
            f"{item.average_concurrent:.0f}"
            if item.average_concurrent is not None
            else "-"
        )
        print(
            f"{position:>2}. {item.name:<30} "
            f"language={item.language:<10} "
            f"videos={item.video_count:<3} "
            f"views={item.total_views:<10} "
            f"avg_concurrent={avg_concurrent}"
        )


if __name__ == "__main__":
    main()
