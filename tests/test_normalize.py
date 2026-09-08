from datetime import datetime, timezone

from collector.youtube.collector import normalize_video


def test_normalize_live_video() -> None:
    observed_at = datetime(2026, 9, 8, tzinfo=timezone.utc)
    video = {
        "id": "abc123",
        "snippet": {
            "title": "Breaking News",
            "publishedAt": "2026-09-08T10:00:00Z",
        },
        "statistics": {
            "viewCount": "12345",
            "likeCount": "678",
            "commentCount": "90",
        },
        "liveStreamingDetails": {
            "actualStartTime": "2026-09-08T10:01:00Z",
            "concurrentViewers": "4321",
        },
    }

    result = normalize_video(video, "channel1", observed_at)

    assert result.video_id == "abc123"
    assert result.view_count == 12345
    assert result.concurrent_viewers == 4321
    assert result.is_live is True
    assert result.live_ended_at is None


def test_normalize_regular_video() -> None:
    result = normalize_video(
        {
            "id": "xyz789",
            "snippet": {"title": "Report"},
            "statistics": {"viewCount": "100"},
        },
        "channel1",
        datetime.now(timezone.utc),
    )

    assert result.view_count == 100
    assert result.concurrent_viewers is None
    assert result.is_live is False
