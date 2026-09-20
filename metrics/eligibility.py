"""Measurement eligibility rules for STAXIS observations."""

from __future__ import annotations

from collector.classification import VideoClassification


def eligible_for_vod_views(classification: str) -> bool:
    """Return whether an observation can contribute to VOD view metrics."""
    return classification == VideoClassification.REGULAR_VIDEO.value


def eligible_for_shorts_views(classification: str) -> bool:
    """Return whether an observation counts towards Shorts view metrics (kept separate from long-form)."""
    return classification == VideoClassification.SHORT.value


def eligible_for_live_concurrent(classification: str) -> bool:
    """Return whether an observation can contribute to live audience metrics."""
    return classification == VideoClassification.LIVE.value


def eligible_for_any_ranking(classification: str) -> bool:
    """Return whether an observation belongs in the current audience snapshot."""
    return classification in {
        VideoClassification.REGULAR_VIDEO.value,
        VideoClassification.LIVE.value,
    }
