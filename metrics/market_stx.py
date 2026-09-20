"""Production STX snapshots for market-level channel intelligence."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from metrics.acceleration import latest_acceleration
from metrics.competition import CompetitionPoint, build_competition
from metrics.engine import ObservationPoint
from metrics.signal_factory import build_stx_signals
from metrics.stx_index import calculate_stx_index, stx_display
from metrics.timeseries import compare_metric
from metrics.velocity import latest_velocity


def build_market_stx(current_rows: list[dict[str, Any]], previous_rows: list[dict[str, Any]], *, channel_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Calculate explainable STX v0 directly from persisted market observations."""
    current = _group(current_rows)
    previous = _group(previous_rows)
    current_points = [CompetitionPoint(str(cid), _channel_name(rows), _view_delta(rows), _view_velocity(rows)) for cid, rows in current.items() if cid in channel_ids]
    previous_points = [CompetitionPoint(str(cid), _channel_name(rows), _view_delta(rows), _view_velocity(rows)) for cid, rows in previous.items() if cid in channel_ids]
    standings = {item.channel_id: item for item in build_competition(current_points, previous_points)}
    result: dict[int, dict[str, Any]] = {}
    for channel_id in channel_ids:
        rows = current.get(channel_id, [])
        if not rows:
            result[channel_id] = _empty()
            continue
        observations = _observations(rows)
        previous_obs = _observations(previous.get(channel_id, []))
        last = observations[-1]
        previous_last = previous_obs[-1] if previous_obs else None
        signals = build_stx_signals(
            audience_change=compare_metric(previous_last.concurrent_viewers if previous_last else None, last.concurrent_viewers),
            growth_change=compare_metric(previous_last.view_count if previous_last else None, last.view_count),
            velocity=latest_velocity(observations),
            acceleration=latest_acceleration(observations),
            standing=standings.get(str(channel_id)),
            observations=observations,
        )
        index = calculate_stx_index(signals)
        result[channel_id] = {
            "score": round(index.score, 2) if index.score is not None else None,
            "confidence": index.confidence,
            **stx_display(index.score, index.confidence),
            "available_signals": index.available_signals,
            "components": {name: round(value, 2) for name, value in index.component_scores.items()},
            "signals": {name: getattr(signals, name) for name in ("audience", "growth", "momentum", "acceleration", "consistency", "competitive_position", "anomaly_event")},
            "provenance": {"source": "persisted_stataxis_observations", "observation_count": len(observations), "previous_observation_count": len(previous_obs), "missing_values_are_not_zero_filled": True},
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
    return [ObservationPoint(observed_at=row["observed_at"], view_count=row["view_count"], concurrent_viewers=row["concurrent_viewers"], like_count=row["like_count"], comment_count=row["comment_count"]) for row in rows]


def _view_delta(rows: list[dict[str, Any]]) -> float | None:
    """Aggregate per-video view deltas; never subtract unrelated videos."""
    by_video: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        video_id = row.get("video_id")
        if video_id is None:
            return None
        by_video[int(video_id)].append(row)
    total = 0.0
    seen = False
    for video_rows in by_video.values():
        values = [row["view_count"] for row in sorted(video_rows, key=lambda row: row["observed_at"]) if row["view_count"] is not None]
        if len(values) < 2:
            continue
        total += max(0.0, float(values[-1]) - float(values[0]))
        seen = True
    return total if seen else None


def _view_velocity(rows: list[dict[str, Any]]) -> float | None:
    velocity = latest_velocity(_observations(rows))
    return velocity.view_velocity_per_minute if velocity else None


def _channel_name(rows: list[dict[str, Any]]) -> str:
    return str(rows[0].get("channel_name") or rows[0].get("channel") or "Channel") if rows else "Channel"


def _empty() -> dict[str, Any]:
    return {"score": None, "confidence": 0.0, "available_signals": 0, **stx_display(None, 0.0), "components": {}, "signals": {}, "provenance": {"source": "persisted_stataxis_observations", "observation_count": 0, "previous_observation_count": 0, "missing_values_are_not_zero_filled": True}}
