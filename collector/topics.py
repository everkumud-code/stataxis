"""Pure title-to-topic classification using configured English and Hindi keywords."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_topic_keywords(path: Path | None = None) -> dict[str, list[str]]:
    payload = json.loads((path or ROOT / "config" / "topics.json").read_text(encoding="utf-8"))
    return {str(topic): [str(keyword).casefold() for keyword in keywords] for topic, keywords in payload["topics"].items()}


def assign_topic(title: str, keywords: dict[str, list[str]] | None = None) -> str:
    """Assign the first configured matching topic; unmatched titles are Other."""
    value = (title or "").casefold()
    rules = keywords if keywords is not None else load_topic_keywords()
    for topic in ("Politics", "Current Affairs", "Entertainment", "Sports", "Business"):
        if any(keyword in value for keyword in rules.get(topic, [])):
            return topic
    return "Other"
