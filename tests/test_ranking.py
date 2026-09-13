from metrics.ranking import (
    ChannelSnapshot,
    build_snapshot,
    rank_channels,
    rank_channels_by_live,
)


def test_build_snapshot_aggregates_views_and_concurrency():
    snapshot = build_snapshot(
        "ch1",
        "Alpha News",
        "Hindi",
        [100, 200, None],
        [10, 30, None],
    )

    assert snapshot.total_views == 300
    assert snapshot.video_count == 2
    assert snapshot.average_views == 150
    assert snapshot.average_concurrent == 20
    assert snapshot.peak_concurrent == 30


def test_build_snapshot_with_no_views_or_concurrency():
    snapshot = build_snapshot(
        "ch1",
        "Alpha News",
        "Hindi",
        [],
        [],
    )

    assert snapshot.total_views == 0
    assert snapshot.video_count == 0
    assert snapshot.average_views is None
    assert snapshot.average_concurrent is None
    assert snapshot.peak_concurrent is None


def test_rank_channels_orders_by_total_views_then_average():
    channels = [
        ChannelSnapshot(
            "b",
            "Beta",
            "Hindi",
            1000,
            10,
            100,
            None,
            None,
        ),
        ChannelSnapshot(
            "a",
            "Alpha",
            "Hindi",
            2000,
            10,
            200,
            None,
            None,
        ),
        ChannelSnapshot(
            "c",
            "Gamma",
            "Hindi",
            1000,
            10,
            150,
            None,
            None,
        ),
    ]

    ranked = rank_channels(channels)

    assert [item.channel_id for item in ranked] == ["a", "c", "b"]


def test_rank_channels_by_live_orders_by_average_then_peak():
    channels = [
        ChannelSnapshot("a", "Alpha", "Hindi", 0, 0, None, 100, 300),
        ChannelSnapshot("b", "Beta", "Hindi", 0, 0, None, 200, 250),
        ChannelSnapshot("c", "Gamma", "Hindi", 0, 0, None, 200, 400),
        ChannelSnapshot("d", "Delta", "Hindi", 0, 0, None, None, None),
    ]

    ranked = rank_channels_by_live(channels)

    assert [item.channel_id for item in ranked] == ["c", "b", "a", "d"]
