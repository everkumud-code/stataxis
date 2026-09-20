"""Find YouTube channel IDs for candidate channels, for human review.

Channels are never registered automatically from a name search: a search can return a fan
or re-upload channel. This tool only records the top matches for each candidate; a person
approves one, and ``python -m collector.candidate_importer --add-verified`` then re-verifies
the ID against the API and registers it.

    python -m collector.resolve_candidates --resolve --limit 20     # search (100 quota units each)
    python -m collector.resolve_candidates --list                   # show what needs review
    python -m collector.resolve_candidates --approve "Zee News"     # accept the best suggestion
    python -m collector.resolve_candidates --approve "Zee News" --pick 2
"""

from __future__ import annotations

import argparse
import re
from typing import Any

from collector.candidate_importer import load_candidates, save_candidates

SEARCH_COST_UNITS = 100
PENDING_STATUSES = {"pending", "not_found"}


def _normalize(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def rank_suggestions(name: str, found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exact title matches first, then the larger audience: real channels dwarf clones."""
    target = _normalize(name)
    ranked = []
    for item in found:
        exact = _normalize(item.get("title")) == target
        ranked.append({**item, "match": "exact" if exact else "similar"})
    ranked.sort(key=lambda item: (item["match"] != "exact", -(item.get("subscriber_count") or 0)))
    return ranked


def resolve_pending(candidates: list[dict[str, Any]], client: Any, *, limit: int = 20, max_results: int = 3) -> dict[str, int]:
    """Search for candidates without an ID; returns counts. Already-searched candidates are skipped."""
    searched = found = missing = 0
    for candidate in candidates:
        if searched >= limit:
            break
        if candidate.get("channel_id") or candidate.get("suggestions"):
            continue
        if candidate.get("verification_status", "pending") not in PENDING_STATUSES:
            continue
        query = f"{candidate['name']} {candidate.get('network', '')}".strip()
        suggestions = rank_suggestions(candidate["name"], client.search_channels(query, max_results=max_results))
        searched += 1
        if suggestions:
            candidate["suggestions"] = suggestions
            candidate["verification_status"] = "needs_review"
            found += 1
        else:
            candidate["verification_status"] = "not_found"
            missing += 1
    return {"searched": searched, "with_suggestions": found, "not_found": missing, "quota_units": searched * SEARCH_COST_UNITS}


def approve(candidates: list[dict[str, Any]], name: str, pick: int = 1) -> dict[str, Any]:
    """Accept suggestion number ``pick`` (1 = best) for the named candidate."""
    matches = [item for item in candidates if _normalize(item.get("name")) == _normalize(name)]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one candidate named {name!r}, found {len(matches)}")
    candidate = matches[0]
    suggestions = candidate.get("suggestions") or []
    if not 1 <= pick <= len(suggestions):
        raise ValueError(f"pick must be between 1 and {len(suggestions)}")
    chosen = suggestions[pick - 1]
    candidate["channel_id"] = chosen["channel_id"]
    candidate["verification_status"] = "pending"  # the importer verifies it against the API next
    candidate["approved_title"] = chosen.get("title")
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve and approve STAXIS channel candidates.")
    parser.add_argument("--resolve", action="store_true", help="search YouTube for candidates that have no channel ID")
    parser.add_argument("--limit", type=int, default=20, help="maximum searches per run (100 quota units each)")
    parser.add_argument("--list", action="store_true", help="list candidates that need review")
    parser.add_argument("--approve", metavar="NAME", help="accept a suggestion for the named candidate")
    parser.add_argument("--pick", type=int, default=1, help="which suggestion to accept (default: best)")
    args = parser.parse_args()

    candidates = load_candidates()
    if args.resolve:
        from collector.youtube.client import YouTubeClient

        with YouTubeClient() as client:
            print(resolve_pending(candidates, client, limit=args.limit))
        save_candidates(candidates)
    if args.approve:
        chosen = approve(candidates, args.approve, args.pick)
        save_candidates(candidates)
        print(f"Approved {chosen['name']} -> {chosen['channel_id']} ({chosen.get('approved_title')})")
    if args.list:
        for item in candidates:
            if item.get("verification_status") == "needs_review":
                print(f"\n{item['name']} [{item.get('segment', 'news')}, {item['language']}]")
                for number, suggestion in enumerate(item.get("suggestions", []), start=1):
                    print(f"  {number}. {suggestion['title']}  {suggestion['channel_id']}  "
                          f"subs={suggestion.get('subscriber_count')}  {suggestion.get('handle') or ''}  [{suggestion['match']}]")


if __name__ == "__main__":
    main()
