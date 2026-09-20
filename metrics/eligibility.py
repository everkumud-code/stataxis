"""Measurement eligibility rules for STAXIS observations."""

from __future__ import annotations

from sqlalchemy import or_

from collector.classification import VideoClassification
from collector.storage import Observation


def counted_in_analysis(classification: str | None) -> bool:
    """Shorts are displayed but never counted in analysis, rankings or STX."""
    return classification != VideoClassification.SHORT.value


def analysis_observation_clause():
    """SQL predicate selecting the observations that count towards analysis and STX."""
    return or_(Observation.classification.is_(None), Observation.classification != VideoClassification.SHORT.value)


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
