from datetime import UTC, datetime

import pytest

from api.media_intelligence import _scope_matches
from collector.classification import (
    VideoClassification,
    classify_video,
    is_short_duration,
    parse_iso8601_duration_seconds,
)
from collector.youtube.collector import normalize_video
from metrics.eligibility import eligible_for_shorts_views, eligible_for_vod_views


def video(duration, published="2026-08-01T10:00:00Z", broadcast="none", live=None):
    item = {
        "id": "abc",
        "snippet": {"liveBroadcastContent": broadcast, "publishedAt": published, "title": "t"},
        "contentDetails": {"duration": duration} if duration else {},
        "statistics": {"viewCount": "10"},
    }
    if live:
        item["liveStreamingDetails"] = live
    return item


@pytest.mark.parametrize("value,expected", [
    ("PT45S", 45), ("PT1M15S", 75), ("PT3M", 180), ("PT1H2M3S", 3723), ("P1DT1S", 86401),
    ("P0D", 0), ("P", None), ("garbage", None), (None, None), (75, None),
])
def test_iso8601_duration_parsing(value, expected):
    assert parse_iso8601_duration_seconds(value) == expected


def test_three_minute_limit_is_inclusive_for_recent_uploads():
    assert classify_video(video("PT2M59S")) == VideoClassification.SHORT.value
    assert classify_video(video("PT3M")) == VideoClassification.SHORT.value
    assert classify_video(video("PT3M1S")) == VideoClassification.REGULAR_VIDEO.value


def test_uploads_before_15_oct_2024_use_the_old_one_minute_limit():
    assert classify_video(video("PT59S", published="2024-06-01T00:00:00Z")) == VideoClassification.SHORT.value
    assert classify_video(video("PT2M", published="2024-06-01T00:00:00Z")) == VideoClassification.REGULAR_VIDEO.value
    assert classify_video(video("PT2M", published="2024-10-15T00:00:00Z")) == VideoClassification.SHORT.value


def test_missing_duration_stays_regular_video_and_zero_is_not_a_short():
    assert classify_video(video(None)) == VideoClassification.REGULAR_VIDEO.value
    assert is_short_duration(0) is False
    assert is_short_duration(None) is False


def test_live_and_replay_are_never_classified_as_shorts():
    live = {"actualStartTime": "2026-09-01T00:00:00Z"}
    assert classify_video(video("PT0S", broadcast="live", live=live)) == VideoClassification.LIVE.value
    replay = {"actualStartTime": "2026-09-01T00:00:00Z", "actualEndTime": "2026-09-01T00:02:00Z"}
    assert classify_video(video("PT2M", broadcast="none", live=replay)) == VideoClassification.COMPLETED_LIVE.value


def test_normalized_short_is_not_live_and_counts_as_shorts_not_long_form():
    observation = normalize_video(video("PT58S"), "c", datetime(2026, 9, 20, tzinfo=UTC))
    assert observation.classification == "SHORT"
    assert observation.is_live is False
    assert eligible_for_shorts_views(observation.classification) is True
    assert eligible_for_vod_views(observation.classification) is False


def test_shorts_stream_scope_is_separate_from_long_form_videos():
    short = {"classification": "SHORT", "is_live": False}
    regular = {"classification": "REGULAR_VIDEO", "is_live": False}
    assert _scope_matches(short, "shorts") and not _scope_matches(regular, "shorts")
    assert _scope_matches(regular, "video") and not _scope_matches(short, "video")
    # "all" is the counted scope: Shorts are excluded from it.
    assert _scope_matches(regular, "all") and not _scope_matches(short, "all")
    with pytest.raises(ValueError, match="shorts"):
        _scope_matches(short, "bogus")
