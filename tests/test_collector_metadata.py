from pathlib import Path
import json

from collector.main import load_targets


def test_load_targets_reads_optional_region_and_language(tmp_path: Path) -> None:
    path = tmp_path / "channels.json"
    path.write_text(json.dumps({
        "channels": [
            {
                "channel_id": "channel-1",
                "name": "Configured",
                "language": "Hindi",
                "region": "North India",
                "network": "Network",
            },
            {
                "channel_id": "channel-2",
                "name": "Missing Region",
                "language": "English",
                "network": "Network",
            },
            {
                "channel_id": "channel-3",
                "name": "Missing Language",
                "region": "South India",
                "network": "Network",
            },
        ]
    }), encoding="utf-8")

    targets = load_targets(path)

    assert targets[0].language == "Hindi"
    assert targets[0].region == "North India"
    assert targets[1].language == "English"
    assert targets[1].region is None
    assert targets[2].language == "unknown"
    assert targets[2].region == "South India"
