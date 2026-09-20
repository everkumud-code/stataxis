from api.evaluate import EvaluationResult


def test_evaluation_result_exposes_display_stx_fields():
    result = EvaluationResult(
        video_id=1,
        youtube_video_id="video-display",
        display_name="Display",
        channel_id=2,
        channel_name="Channel",
        observation_saved=True,
        observation_count=2,
        stx_index=100.0,
        confidence=10.0,
        available_signals=1,
        data=[],
        analysis=[],
        view="",
        display_stx_index=55.0,
        preliminary=True,
    )

    payload = result.as_dict()
    assert payload["stx_index"] == 100.0
    assert payload["confidence"] == 10.0
    assert payload["display_stx_index"] == 55.0
    assert payload["preliminary"] is True
