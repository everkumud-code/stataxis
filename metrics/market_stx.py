"""Production STX snapshots for market-level channel intelligence."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from metrics.acceleration import latest_acceleration
from metrics.competition import CompetitionPoint, build_competition
from metrics.engine import ObservationPoint
from metrics.signal_factory import build_stx_signals
from metrics.stx_index import calculate_stx_index
from metrics.timeseries import compare_metric
from metrics.velocity import latest_velocity


def build_market_stx(
    current_rows: list[dict[str, Any]],
    previous_rows: list[dict[str, Any]],
    *,
    channel_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """Calculate explainable STX v0 directly from persisted market observations."""
    current = _group(current_rows)
    previous = _group(previous_rows)
    current_points = [
        CompetitionPoint(str(channel_id), _channel_name(rows), _view_delta(rows), _view_velocity(rows))
        for channel_id, rows in current.items()
        if channel_id in channel_ids
    ]
    previous_points = [
        CompetitionPoint(str(channel_id), _channel_name(rows), _view_delta(rows), _view_velocity(rows))
        for channel_id, rows in previous.items()
        if channel_id in channel_ids
    ]
    standings = {item.channel_id: item for item in build_competition(current_points, previous_points)}

    result: dict[int, dict[str, Any]] = {}
    for channel_id in channel_ids:
        rows = current.get(channel_id, [])
        if not rows:
            result[channel_id] = _empty()
            continue
        observations = _observations(rows)
        previous_obs = _observations(previous.get(channel_id, []))
        first = observations[0] if observations else None
        last = observations[-1] if observations else None
        previous_last = previous_obs[-1] if previous_obs else None
        audience_change = compare_metric(
            previous_last.concurrent_viewers if previous_last else None,
            last.concurrent_viewers if last else None,
        )
        growth_change = compare_metric(
            previous_last.view_count if previous_last else None,
            last.view_count if last else None,
        )
        velocity = latest_velocity(observations)
        acceleration = latest_acceleration(observations)
        signals = build_stx_signals(
            audience_change=audience_change,
            growth_change=growth_change,
            velocity=velocity,
            acceleration=acceleration,
            standing=standings.get(str(channel_id)),
            observations=observations,
        )
        index = calculate_stx_index(signals)
        result[channel_id] = {
            "score": round(index.score, 2) if index.score is not None else None,
            "confidence": index.confidence,
            "available_signals": index.available_signals,
            "components": {name: round(value, 2) for name, value in index.component_scores.items()},
            "signals": {
                "audience": signals.audience,
                "growth": signals.growth,
                "momentum": signals.momentum,
                "acceleration": signals.acceleration,
                "consistency": signals.consistency,
                "competitive_position": signals.competitive_position,
                "anomaly_event": signals.anomaly_event,
            },
        }
    return result


def _group(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["channel_id"])].append(row)
    for values in grouped.values():
        values.sort(key=lambda row: row["observed_at"])
    return grouped


def _observations(rows: list[dict[str, Any]]) -> list[ObservationPoint]:
    return [
        ObservationPoint(
            observed_at=row["observed_at"],
            view_count=row["view_count"],
            concurrent_viewers=row["concurrent_viewers"],
            like_count=row["like_count"],
            comment_count=row["comment_count"],
        )
        for row in rows
    ]


def _view_delta(rows: list[dict[str, Any]]) -> float | None:
    usable = [row["view_count"] for row in rows if row["view_count"] is not None]
    if len(usable) < 2:
        return None
    return max(0, float(usable[-1]) - float(usable[0]))


def _view_velocity(rows: list[dict[str, Any]]) -> float | None:
    observations = _observations(rows)
    velocity = latest_velocity(observations)
    return velocity.view_velocity_per_minute if velocity else None


def _channel_name(rows: list[dict[str, Any]]) -> str:
    return str(rows[0].get("channel_name") or rows[0].get("channel") or "Channel") if rows else "Channel"


def _empty() -> dict[str, Any]:
    return {"score": None, "confidence": 0.0, "available_signals": 0, "components": {}, "signals": {}}
