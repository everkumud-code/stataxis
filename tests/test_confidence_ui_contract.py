from pathlib import Path


DASHBOARD = Path(__file__).parents[1] / "dashboard"


def test_ui_confidence_contract_uses_backend_0_to_100_values():
    # The UI displays Math.round(value)%; for the canonical backend value 65,
    # the displayed percentage must therefore be 65%, not 6500%.
    assert round(65) == 65

    sources = [
        (DASHBOARD / "app.js").read_text(),
        (DASHBOARD / "evaluate.js").read_text(),
        (DASHBOARD / "live.js").read_text(),
        (DASHBOARD / "media-intelligence.js").read_text(),
    ]
    assert all("confidence * 100" not in source for source in sources)
    assert all("confidence)*100" not in source for source in sources)
