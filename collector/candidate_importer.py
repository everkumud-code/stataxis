import json
from pathlib import Path

from collector.channel_registry import add_channel, channel_exists
from collector.verify_channel import verify_channel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANDIDATES_FILE = PROJECT_ROOT / "config" / "channel_candidates.json"


def load_candidates() -> list[dict]:
    if not CANDIDATES_FILE.exists():
        raise FileNotFoundError(
            f"Candidate file not found: {CANDIDATES_FILE}"
        )

    with CANDIDATES_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return data.get("candidates", [])


def save_candidates(candidates: list[dict]) -> None:
    with CANDIDATES_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            {"candidates": candidates},
            file,
            indent=2,
            ensure_ascii=False,
        )


def process_candidates(add_verified: bool = False) -> None:
    candidates = load_candidates()

    print()
    print("STAXIS CANDIDATE VERIFICATION")
    print("=" * 70)

    verified = 0
    pending = 0
    failed = 0
    duplicates = 0
    added = 0

    for candidate in candidates:
        name = candidate.get("name")
        channel_id = candidate.get("channel_id")

        print()
        print(f"Candidate: {name}")

        if not channel_id:
            print("Status:    PENDING — no channel ID yet")
            pending += 1
            continue

        if channel_exists(channel_id):
            candidate["verification_status"] = "registered"
            print("Status:    REGISTERED — already in registry")
            duplicates += 1
            continue

        try:
            result = verify_channel(channel_id)

            candidate["verification_status"] = "verified"
            candidate["verified_title"] = result["title"]
            candidate["verified_channel_id"] = result["channel_id"]
            candidate["uploads_playlist_id"] = result["uploads_playlist_id"]

            print("Status:    VERIFIED")
            print(f"YouTube:   {result['title']}")
            print(f"Channel ID:{result['channel_id']}")

            verified += 1

            if add_verified:
                add_channel(
                    channel_id=result["channel_id"],
                    name=name,
                    language=candidate["language"],
                    network=candidate["network"],
                    segment=candidate.get("segment", "news"),
                )

                candidate["verification_status"] = "registered"

                print("Registry:  ADDED")
                added += 1

        except ValueError as exc:
            candidate["verification_status"] = "failed"
            candidate["verification_error"] = str(exc)

            print("Status:    FAILED")
            print(f"Reason:    {exc}")

            failed += 1

    save_candidates(candidates)

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Verified:   {verified}")
    print(f"Pending:    {pending}")
    print(f"Failed:     {failed}")
    print(f"Registered: {duplicates + added}")
    print(f"Added now:  {added}")
    print("=" * 70)
    print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Verify and optionally register Stataxis channel candidates."
    )

    parser.add_argument(
        "--add-verified",
        action="store_true",
        help="Add successfully verified candidates to the channel registry.",
    )

    args = parser.parse_args()

    process_candidates(add_verified=args.add_verified)
