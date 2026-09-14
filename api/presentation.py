"""Stable presentation payloads for dashboard/API consumers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from metrics.explain import explain_index
from metrics.fusion import FusedIntelligence


def intelligence_payload(result: FusedIntelligence) -> dict[str, Any]:
    """Convert fused intelligence into a JSON-safe, UI-friendly payload."""
    return {
        "stx_index": {
            "score": result.index.score,
            "confidence": result.index.confidence,
            "available_signals": result.index.available_signals,
        },
        "data": list(result.view.data),
        "analysis": list(result.view.analysis),
        "view": result.view.view,
        "signal_contributions": [asdict(item) for item in explain_index(result.index)],
    }
