from collector.classification import VideoClassification


def test_video_classification_values():
    assert VideoClassification.LIVE.value == "LIVE"
    assert VideoClassification.REGULAR_VIDEO.value == "REGULAR_VIDEO"
    assert VideoClassification.SHORT.value == "SHORT"
    assert VideoClassification.PREMIERE.value == "PREMIERE"
    assert VideoClassification.REPLAY.value == "REPLAY"
    assert VideoClassification.UNKNOWN.value == "UNKNOWN"