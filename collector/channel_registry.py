import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = PROJECT_ROOT / "config" / "channels.json"


def load_channels() -> list[dict]:
    if not CONFIG_FILE.exists():
        return []

    with CONFIG_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return data.get("channels", [])


def save_channels(channels: list[dict]) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

    with CONFIG_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            {"channels": channels},
            file,
            indent=2,
            ensure_ascii=False,
        )


def channel_exists(channel_id: str) -> bool:
    return any(channel["channel_id"] == channel_id for channel in load_channels())


def add_channel(
    channel_id: str,
    name: str,
    language: str,
    network: str,
    segment: str = "news",
) -> None:
    channels = load_channels()

    if channel_exists(channel_id):
        raise ValueError(f"Channel already exists: {channel_id}")

    channels.append(
        {
            "channel_id": channel_id,
            "name": name,
            "language": language,
            "network": network,
            "segment": segment,
        }
    )

    save_channels(channels)
