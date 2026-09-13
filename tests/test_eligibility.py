from collector.classification import VideoClassification
from metrics.eligibility import (
    eligible_for_any_ranking,
    eligible_for_live_concurrent,
    eligible_for_vod_views,
)


def test_regular_video_is_eligible_for_vod_views():
    assert eligible_for_vod_views(VideoClassification.REGULAR_VIDEO.value)


def test_live_is_eligible_for_live_concurrent():
    assert eligible_for_live_concurrent(VideoClassification.LIVE.value)


def test_upcoming_is_not_eligible_for_ranking():
    assert not eligible_for_any_ranking(VideoClassification.UPCOMING.value)


def test_unknown_is_not_eligible_for_ranking():
    assert not eligible_for_any_ranking(VideoClassification.UNKNOWN.value)


def test_completed_live_is_not_eligible_for_current_vod_or_live_metrics():
    classification = VideoClassification.COMPLETED_LIVE.value
    assert not eligible_for_vod_views(classification)
    assert not eligible_for_live_concurrent(classification)
