"""Channel ranking calculations for the first STAXIS public ranking layer."""

from __future__ import annotations

from dataclasses import dataclass

from metrics.engine import average


@dataclass(frozen=True)
class ChannelSnapshot:
    """Aggregated channel measurements for one ranking window."""

    channel_id: str
    name: str
    language: str
    total_views: int
    video_count: int
    average_views: float | None
    average_concurrent: float | None
    peak_concurrent: int | None


def rank_channels(channels: list[ChannelSnapshot]) -> list[ChannelSnapshot]:
    """Rank channels by total observed views, then average views, then name."""
    return sorted(
        channels,
        key=lambda item: (
            -item.total_views,
            -(item.average_views if item.average_views is not None else -1),
            item.name.lower(),
        ),
    )


def build_snapshot(
    channel_id: str,
    name: str,
    language: str,
    view_counts: list[int | None],
    concurrent_counts: list[int | None],
) -> ChannelSnapshot:
    """Build a channel snapshot from observed video-level values."""
    usable_views = [value for value in view_counts if value is not None]
    usable_concurrent = [value for value in concurrent_counts if value is not None]
    return ChannelSnapshot(
        channel_id=channel_id,
        name=name,
        language=language,
        total_views=sum(usable_views),
        video_count=len(usable_views),
        average_views=average(usable_views),
        average_concurrent=average(usable_concurrent),
        peak_concurrent=max(usable_concurrent) if usable_concurrent else None,
    )
