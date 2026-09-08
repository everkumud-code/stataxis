from collector.classification import (
    VideoClassification,
    classify_video,
)


def test_classify_active_live_video():
    video = {
        "snippet": {
            "liveBroadcastContent": "live",
        },
        "liveStreamingDetails": {
            "actualStartTime": "2026-09-08T10:00:00Z",
        },
    }

    assert classify_video(video) == VideoClassification.LIVE.value


def test_classify_completed_live_video():
    video = {
        "snippet": {
            "liveBroadcastContent": "none",
        },
        "liveStreamingDetails": {
            "actualStartTime": "2026-09-08T10:00:00Z",
            "actualEndTime": "2026-09-08T11:00:00Z",
        },
    }

    assert classify_video(video) == VideoClassification.COMPLETED_LIVE.value


def test_classify_regular_video():
    video = {
        "snippet": {
            "liveBroadcastContent": "none",
        },
        "contentDetails": {
            "duration": "PT12M30S",
        },
    }

    assert classify_video(video) == VideoClassification.REGULAR_VIDEO.value


def test_classify_unknown_video():
    video = {}

    assert classify_video(video) == VideoClassification.UNKNOWN.value


def test_video_classification_values():
    assert VideoClassification.LIVE.value == "LIVE"
    assert VideoClassification.COMPLETED_LIVE.value == "COMPLETED_LIVE"
    assert VideoClassification.REGULAR_VIDEO.value == "REGULAR_VIDEO"
    assert VideoClassification.SHORT.value == "SHORT"
    assert VideoClassification.PREMIERE.value == "PREMIERE"
    assert VideoClassification.REPLAY.value == "REPLAY"
    assert VideoClassification.UNKNOWN.value == "UNKNOWN"