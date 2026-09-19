from datetime import UTC, datetime, timedelta

from metrics.market_stx import build_market_stx


def _row(channel_id: int, observed_at: datetime, views: int, concurrent: int) -> dict:
    return {
        "channel_id": channel_id,
        "channel_name": f"Channel {channel_id}",
        "observed_at": observed_at,
        "view_count": views,
        "concurrent_viewers": concurrent,
        "like_count": 10,
        "comment_count": 2,
    }


def test_market_stx_uses_persisted_history_and_exposes_evidence():
    start = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    current = [
        _row(1, start, 1000, 100),
        _row(1, start + timedelta(minutes=5), 1200, 140),
        _row(2, start, 900, 80),
        _row(2, start + timedelta(minutes=5), 950, 85),
    ]
    previous = [
        _row(1, start - timedelta(hours=1), 700, 90),
        _row(1, start - timedelta(minutes=55), 800, 95),
        _row(2, start - timedelta(hours=1), 700, 75),
        _row(2, start - timedelta(minutes=55), 760, 78),
    ]

    result = build_market_stx(current, previous, channel_ids=[1, 2])

    assert set(result) == {1, 2}
    assert result[1]["score"] is not None
    assert 0 <= result[1]["score"] <= 100
    assert 0 < result[1]["available_signals"] <= 7
    assert result[1]["confidence"] > 0
    assert "audience" in result[1]["components"]
    assert "momentum" in result[1]["components"]


def test_market_stx_does_not_invent_score_without_observations():
    result = build_market_stx([], [], channel_ids=[99])

    assert result[99]["score"] is None
    assert result[99]["available_signals"] == 0
    assert result[99]["confidence"] == 0.0
    assert result[99]["components"] == {}
