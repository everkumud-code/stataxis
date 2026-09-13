"""Competitive intelligence calculations for StatAxis channel comparisons."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompetitionPoint:
    """A channel's comparable measurement for one competition window."""

    channel_id: str
    name: str
    value: float | None
    momentum: float | None = None


@dataclass(frozen=True)
class CompetitiveStanding:
    """Rank, share, gap, and movement signals for one channel."""

    channel_id: str
    name: str
    value: float | None
    rank: int | None
    share: float | None
    previous_rank: int | None
    rank_change: int | None
    previous_share: float | None
    share_change: float | None
    gap_to_leader: float | None
    previous_gap_to_leader: float | None
    gap_change: float | None
    momentum: float | None
    momentum_rank: int | None


@dataclass(frozen=True)
class HeadToHeadResult:
    """Evidence available for a direct comparison between two channels."""

    channel_a: CompetitionPoint
    channel_b: CompetitionPoint
    value_leader: str | None
    value_gap: float | None
    momentum_leader: str | None
    momentum_gap: float | None


def _rank_map(points: list[CompetitionPoint]) -> dict[str, int]:
    """Return competition ranks (1, 1, 3) for available values."""
    ordered = sorted(
        (point for point in points if point.value is not None),
        key=lambda point: (-point.value, point.name.lower(), point.channel_id),
    )
    ranks: dict[str, int] = {}
    previous_value: float | None = None
    previous_rank = 0
    for position, point in enumerate(ordered, start=1):
        if previous_value is None or point.value != previous_value:
            previous_rank = position
            previous_value = point.value
        ranks[point.channel_id] = previous_rank
    return ranks


def _share_map(points: list[CompetitionPoint]) -> dict[str, float | None]:
    """Return relative share within the supplied comparison set."""
    values = [point.value for point in points if point.value is not None]
    total = sum(values)
    if total <= 0:
        return {point.channel_id: None for point in points}
    return {
        point.channel_id: (point.value / total * 100 if point.value is not None else None)
        for point in points
    }


def _gap_map(points: list[CompetitionPoint]) -> dict[str, float | None]:
    """Return each available channel's gap to the current leader."""
    values = [point.value for point in points if point.value is not None]
    if not values:
        return {point.channel_id: None for point in points}
    leader = max(values)
    return {
        point.channel_id: (leader - point.value if point.value is not None else None)
        for point in points
    }


def _momentum_rank_map(points: list[CompetitionPoint]) -> dict[str, int]:
    """Rank available momentum values, with higher momentum ranked first."""
    ordered = sorted(
        (point for point in points if point.momentum is not None),
        key=lambda point: (-point.momentum, point.name.lower(), point.channel_id),
    )
    ranks: dict[str, int] = {}
    previous_value: float | None = None
    previous_rank = 0
    for position, point in enumerate(ordered, start=1):
        if previous_value is None or point.momentum != previous_value:
            previous_rank = position
            previous_value = point.momentum
        ranks[point.channel_id] = previous_rank
    return ranks


def build_competition(
    current: list[CompetitionPoint],
    previous: list[CompetitionPoint] | None = None,
) -> list[CompetitiveStanding]:
    """Build a competition snapshot without treating missing data as zero."""
    current_ranks = _rank_map(current)
    current_shares = _share_map(current)
    current_gaps = _gap_map(current)
    momentum_ranks = _momentum_rank_map(current)

    previous_ranks = _rank_map(previous or [])
    previous_shares = _share_map(previous or [])
    previous_gaps = _gap_map(previous or [])

    standings: list[CompetitiveStanding] = []
    for point in current:
        rank = current_ranks.get(point.channel_id)
        previous_rank = previous_ranks.get(point.channel_id)
        share = current_shares.get(point.channel_id)
        previous_share = previous_shares.get(point.channel_id)
        gap = current_gaps.get(point.channel_id)
        previous_gap = previous_gaps.get(point.channel_id)

        rank_change = (
            previous_rank - rank
            if previous_rank is not None and rank is not None
            else None
        )
        share_change = (
            share - previous_share
            if share is not None and previous_share is not None
            else None
        )
        gap_change = (
            gap - previous_gap
            if gap is not None and previous_gap is not None
            else None
        )

        standings.append(
            CompetitiveStanding(
                channel_id=point.channel_id,
                name=point.name,
                value=point.value,
                rank=rank,
                share=share,
                previous_rank=previous_rank,
                rank_change=rank_change,
                previous_share=previous_share,
                share_change=share_change,
                gap_to_leader=gap,
                previous_gap_to_leader=previous_gap,
                gap_change=gap_change,
                momentum=point.momentum,
                momentum_rank=momentum_ranks.get(point.channel_id),
            )
        )

    return sorted(
        standings,
        key=lambda item: (
            item.rank is None,
            item.rank if item.rank is not None else float("inf"),
            item.name.lower(),
        ),
    )


def compare_head_to_head(
    points: list[CompetitionPoint],
    channel_a_id: str,
    channel_b_id: str,
) -> HeadToHeadResult:
    """Compare two channels without inventing missing observations."""
    by_id = {point.channel_id: point for point in points}
    try:
        channel_a = by_id[channel_a_id]
        channel_b = by_id[channel_b_id]
    except KeyError as exc:
        raise ValueError(f"unknown channel: {exc.args[0]}") from exc

    value_leader = None
    value_gap = None
    if channel_a.value is not None and channel_b.value is not None:
        if channel_a.value > channel_b.value:
            value_leader = channel_a.channel_id
        elif channel_b.value > channel_a.value:
            value_leader = channel_b.channel_id
        value_gap = abs(channel_a.value - channel_b.value)

    momentum_leader = None
    momentum_gap = None
    if channel_a.momentum is not None and channel_b.momentum is not None:
        if channel_a.momentum > channel_b.momentum:
            momentum_leader = channel_a.channel_id
        elif channel_b.momentum > channel_a.momentum:
            momentum_leader = channel_b.channel_id
        momentum_gap = abs(channel_a.momentum - channel_b.momentum)

    return HeadToHeadResult(
        channel_a=channel_a,
        channel_b=channel_b,
        value_leader=value_leader,
        value_gap=value_gap,
        momentum_leader=momentum_leader,
        momentum_gap=momentum_gap,
    )
