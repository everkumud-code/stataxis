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
    momentum_rank: int | None = None


@dataclass(frozen=True)
class CompetitivePosition:
    """Dashboard-ready interpretation of a channel's competitive state."""

    channel_id: str
    label: str
    signals: tuple[str, ...]


@dataclass(frozen=True)
class HeadToHeadResult:
    """Evidence available for a direct comparison between two channels."""

    channel_a: CompetitionPoint
    channel_b: CompetitionPoint
    value_leader: str | None
    value_gap: float | None
    momentum_leader: str | None
    momentum_gap: float | None


@dataclass(frozen=True)
class CompetitiveSummary:
    """Top-level competitive signals derived from a standings snapshot."""

    leader_id: str | None
    momentum_leader_id: str | None
    biggest_rank_gainer_id: str | None
    biggest_rank_loser_id: str | None
    biggest_share_gainer_id: str | None
    biggest_share_loser_id: str | None
    biggest_gap_closer_id: str | None
    biggest_gap_widener_id: str | None
    channels_with_data: int


def _rank_map(points: list[CompetitionPoint]) -> dict[str, int]:
    ordered = sorted((point for point in points if point.value is not None), key=lambda point: (-point.value, point.name.lower(), point.channel_id))
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
    values = [point.value for point in points if point.value is not None]
    total = sum(values)
    if total <= 0:
        return {point.channel_id: None for point in points}
    return {point.channel_id: (round(point.value / total * 100, 12) if point.value is not None else None) for point in points}


def _gap_map(points: list[CompetitionPoint]) -> dict[str, float | None]:
    values = [point.value for point in points if point.value is not None]
    if not values:
        return {point.channel_id: None for point in points}
    leader = max(values)
    return {point.channel_id: (leader - point.value if point.value is not None else None) for point in points}


def _momentum_rank_map(points: list[CompetitionPoint]) -> dict[str, int]:
    ordered = sorted((point for point in points if point.momentum is not None), key=lambda point: (-point.momentum, point.name.lower(), point.channel_id))
    ranks: dict[str, int] = {}
    previous_value: float | None = None
    previous_rank = 0
    for position, point in enumerate(ordered, start=1):
        if previous_value is None or point.momentum != previous_value:
            previous_rank = position
            previous_value = point.momentum
        ranks[point.channel_id] = previous_rank
    return ranks


def build_competition(current: list[CompetitionPoint], previous: list[CompetitionPoint] | None = None) -> list[CompetitiveStanding]:
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
        rank_change = previous_rank - rank if previous_rank is not None and rank is not None else None
        share_change = round(share - previous_share, 12) if share is not None and previous_share is not None else None
        gap_change = gap - previous_gap if gap is not None and previous_gap is not None else None
        standings.append(CompetitiveStanding(point.channel_id, point.name, point.value, rank, share, previous_rank, rank_change, previous_share, share_change, gap, previous_gap, gap_change, point.momentum, momentum_ranks.get(point.channel_id)))
    return sorted(standings, key=lambda item: (item.rank is None, item.rank if item.rank is not None else float("inf"), item.name.lower()))


def classify_competitive_position(standing: CompetitiveStanding) -> CompetitivePosition:
    if standing.value is None or standing.rank is None:
        return CompetitivePosition(standing.channel_id, "insufficient data", ())
    signals: list[str] = []
    if standing.rank == 1:
        signals.append("leader")
    if standing.momentum_rank == 1:
        signals.append("momentum leader")
    if standing.rank_change is not None and standing.rank_change > 0:
        signals.append("rank gaining")
    elif standing.rank_change is not None and standing.rank_change < 0:
        signals.append("rank losing")
    if standing.share_change is not None and standing.share_change > 0:
        signals.append("share gaining")
    elif standing.share_change is not None and standing.share_change < 0:
        signals.append("share losing")
    if standing.gap_change is not None and standing.gap_change < 0:
        signals.append("closing gap")
    elif standing.gap_change is not None and standing.gap_change > 0:
        signals.append("widening gap")
    if standing.rank == 1 and standing.momentum_rank == 1:
        label = "competitive leader"
    elif standing.rank_change is not None and standing.rank_change > 0:
        label = "gaining ground"
    elif standing.rank_change is not None and standing.rank_change < 0:
        label = "losing ground"
    elif standing.momentum_rank == 1:
        label = "momentum leader"
    elif standing.gap_change is not None and standing.gap_change < 0:
        label = "closing the gap"
    elif standing.gap_change is not None and standing.gap_change > 0:
        label = "falling behind"
    else:
        label = "stable position"
    return CompetitivePosition(standing.channel_id, label, tuple(signals))


def _unique_extreme_id(standings: list[CompetitiveStanding], attribute: str, maximize: bool) -> str | None:
    candidates = [item for item in standings if getattr(item, attribute) is not None]
    if not candidates:
        return None
    target = (max if maximize else min)(getattr(item, attribute) for item in candidates)
    winners = [item for item in candidates if getattr(item, attribute) == target]
    return winners[0].channel_id if len(winners) == 1 else None


def summarize_competition(standings: list[CompetitiveStanding]) -> CompetitiveSummary:
    ranked = [item for item in standings if item.rank is not None]
    momentum = [item for item in standings if item.momentum_rank is not None]
    return CompetitiveSummary(
        leader_id=ranked[0].channel_id if ranked else None,
        momentum_leader_id=min(momentum, key=lambda item: item.momentum_rank).channel_id if momentum else None,
        biggest_rank_gainer_id=_unique_extreme_id(standings, "rank_change", True),
        biggest_rank_loser_id=_unique_extreme_id(standings, "rank_change", False),
        biggest_share_gainer_id=_unique_extreme_id(standings, "share_change", True),
        biggest_share_loser_id=_unique_extreme_id(standings, "share_change", False),
        biggest_gap_closer_id=_unique_extreme_id(standings, "gap_change", False),
        biggest_gap_widener_id=_unique_extreme_id(standings, "gap_change", True),
        channels_with_data=len(ranked),
    )


def compare_head_to_head(points: list[CompetitionPoint], channel_a_id: str, channel_b_id: str) -> HeadToHeadResult:
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
    return HeadToHeadResult(channel_a, channel_b, value_leader, value_gap, momentum_leader, momentum_gap)
