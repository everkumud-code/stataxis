"""Platform-neutral digital media signals for cross-platform StatAxis intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Platform(StrEnum):
    """Supported digital platforms at the normalized intelligence layer."""

    YOUTUBE = "youtube"
    X = "x"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"


@dataclass(frozen=True)
class PlatformObservation:
    """Timestamped platform-neutral observation before derived metrics."""

    platform: Platform
    content_id: str
    account_id: str
    display_name: str
    observed_at: float
    exposure: float | None = None
    views: float | None = None
    engagement: float | None = None
    likes: float | None = None
    comments: float | None = None
    shares: float | None = None
    saves: float | None = None
    replies: float | None = None
    reposts: float | None = None
    quotes: float | None = None
    followers: float | None = None
    is_live: bool = False


def engagement_total(observation: PlatformObservation) -> float | None:
    """Return the sum of directly observed interaction signals."""
    values = [
        observation.engagement,
        observation.likes,
        observation.comments,
        observation.shares,
        observation.saves,
        observation.replies,
        observation.reposts,
        observation.quotes,
    ]
    available = [value for value in values if value is not None]
    return sum(available) if available else None


def exposure_rate(observation: PlatformObservation) -> float | None:
    """Return interactions per unit exposure, when both are available."""
    total = engagement_total(observation)
    if total is None or observation.exposure is None or observation.exposure <= 0:
        return None
    return total / observation.exposure * 100


def normalize_display_name(value: str) -> str:
    """Return a clean custom display label for dashboards and reports."""
    name = " ".join(value.strip().split())
    if not name:
        raise ValueError("display_name is required")
    return name[:255]
