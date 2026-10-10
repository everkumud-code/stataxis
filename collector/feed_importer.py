"""Register the channels of a feed list (config/live_news_feeds.json) by their YouTube handle.

The list comes from the owner's spreadsheet of live news feeds: a category, a name and a handle for each channel.
A handle is resolved exactly (channels.list forHandle, 1 quota unit), never by name search. The title YouTube returns is
then compared with the name on the list: a handle that belongs to some other channel is skipped and reported, not registered.
Channels already tracked are left exactly as they are.

    python -m collector.feed_importer            # check only: resolve every handle and print the plan (writes nothing)
    python -m collector.feed_importer --apply    # register the ones that match
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from collector.storage import Channel, create_database
from metrics.markets import SEGMENTS

FEEDS_FILE = Path(__file__).resolve().parents[1] / "config" / "live_news_feeds.json"

# category on the list -> (segment, language, region)
CATEGORY = {
    "Hindi": ("news", "Hindi", "India"), "India English": ("news", "English", "India"), "Bangla": ("news", "Bangla", "India"),
    "Tamil": ("news", "Tamil", "India"), "Telugu": ("news", "Telugu", "India"), "Kannada": ("news", "Kannada", "India"),
    "Business": ("business", "English", "India"), "International": ("news", "English", "International"), "US": ("news", "English", "US"),
    "UK": ("news", "English", "UK"), "Europe": ("news", "English", "Europe"),
    "Journalists (Top 30)": ("journalist", "Hindi", "India"), "Podcasts (Top 10)": ("creator", "Hindi", "India"),
    "Politicians (Top 10)": ("leader", "Hindi", "India"), "Brands (Top 10)": ("brand", "Hindi", "India"), "Influencers (Top 10)": ("creator", "Hindi", "India"),
}
# the few channels whose language or region differs from their category's
LANGUAGE = {"CNBC Awaaz": "Hindi", "Zee Business": "Hindi", "Faye D'Souza": "English", "Mojo Story (Barkha Dutt)": "English", "Jay Shetty Podcast": "English",
            "WTF is – Nikhil Kamath": "English", "The Seen and the Unseen – Amit Varma": "English", "Shashi Tharoor": "English", "The Sham Sharma Show": "Hindi",
            "France 24 (FR)": "French", "BFMTV": "French", "CNEWS": "French", "Euronews Français": "French", "WELT": "German", "ZDFheute": "German",
            "Euronews Deutsch": "German", "RTVE Noticias": "Spanish"}
REGION = {"Jamuna TV": "Bangladesh", "Somoy TV": "Bangladesh", "Channel 24": "Bangladesh", "CNBC Television": "International", "CNBC": "International",
          "Bloomberg": "International", "Jay Shetty Podcast": "International"}


def classify(category: str, name: str) -> dict[str, str]:
    """Segment, language, region and market for one row of the list."""
    if category not in CATEGORY:
        raise ValueError(f"unknown category: {category}")
    segment, language, region = CATEGORY[category]
    assert segment in SEGMENTS, segment
    return {"segment": segment, "language": LANGUAGE.get(name, language), "region": REGION.get(name, region), "market": category.split(" (")[0]}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _words(value: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (value or "").lower()) if len(w) >= 3}


def title_matches(name: str, youtube_title: str) -> bool:
    """True when the YouTube title plausibly is the channel on the list (a shared word, or a close spelling)."""
    a, b = _norm(re.sub(r"\(.*?\)", "", name)), _norm(youtube_title)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    if _words(name) & _words(youtube_title):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.6


def load_feeds(path: Path = FEEDS_FILE) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["channels"]


def import_feeds(session: Session, client: Any, feeds: list[dict[str, Any]], *, apply: bool = False) -> dict[str, Any]:
    """Resolve each handle and register the matches. Returns the report: added, already_tracked, mismatched, failed, duplicates."""
    report: dict[str, list] = {"added": [], "already_tracked": [], "mismatched": [], "failed": [], "duplicates": []}
    seen: set[str] = set()
    for item in feeds:
        ref, name = item["ref"], item["name"]
        if ref.lower() in seen:
            report["duplicates"].append(f"{name} ({ref}) is listed twice; kept the first")
            continue
        seen.add(ref.lower())
        info = classify(item["category"], name)
        try:
            meta = client.resolve_channel_url(f"https://www.youtube.com/{ref}")
        except Exception as exc:  # a handle that does not resolve is reported, never guessed
            report["failed"].append({"name": name, "ref": ref, "error": str(exc)[:160]})
            continue
        channel_id = str(meta.get("id") or "").strip()
        title = str((meta.get("snippet") or {}).get("title") or "")
        if not channel_id or not title_matches(name, title):
            report["mismatched"].append({"name": name, "ref": ref, "youtube_title": title})
            continue
        row = session.query(Channel).filter_by(youtube_channel_id=channel_id).one_or_none()
        if row is not None:
            report["already_tracked"].append({"name": row.name, "ref": ref})
            continue
        if apply:
            session.add(Channel(youtube_channel_id=channel_id, name=name, network=info["market"], language=info["language"], region=info["region"],
                                active=True, segment=info["segment"], handle=ref if ref.startswith("@") else None))
            session.commit()
        report["added"].append({"name": name, "ref": ref, "segment": info["segment"], "language": info["language"], "youtube_title": title})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Register the channels on the live news feed list.")
    parser.add_argument("--apply", action="store_true", help="write the matching channels (default: check only)")
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is not configured")
    from collector.youtube.client import YouTubeClient
    engine = create_database(database_url)
    with YouTubeClient() as client, Session(engine) as session:
        report = import_feeds(session, client, load_feeds(), apply=args.apply)
    print(json.dumps({k: (len(v) if k in ("added", "already_tracked") else v) for k, v in report.items()}, ensure_ascii=False, indent=1))
    print("registered" if args.apply else "check only; nothing written", [r["name"] for r in report["added"]][:200])


if __name__ == "__main__":
    main()
