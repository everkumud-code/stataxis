from datetime import UTC, datetime
\nfrom metrics.market_stx import build_market_stx


def _row(video_id, observed_at, views):
    return {"channel_id": 1, "channel_name": "Alpha", "video_id": video_id, "observed_at": observed_at, "view_count": views, "concurrent_viewers": 50, "like_count": None, "comment_count": None}


def test_stx_provenance_and_missing_data_are_explicit():
    result = build_market_stx([], [], channel_ids=[99])[99]
    assert result["score"] is None
    assert result["confidence"] == 0.0
    assert result["available_signals"] == 0
    assert result["provenance"]["source"] == "persisted_stataxis_observations"


def test_competitive_delta_never_crosses_video_boundaries():
    result = build_market_stx([
        _row(1, datetime(2026, 9, 16, 10, 0, tzinfo=UTC), 100), _row(2, datetime(2026, 9, 16, 10, 1, tzinfo=UTC), 1000), _row(1, datetime(2026, 9, 16, 10, 3, tzinfo=UTC), 160), _row(2, datetime(2026, 9, 16, 10, 4, tzinfo=UTC), 1125)
    ], [], channel_ids=[1])[1]
    assert result["provenance"]["observation_count"] == 4
