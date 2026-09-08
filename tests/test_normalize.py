from datetime import datetime, timezone

from collector.youtube.collector import normalize_video


def test_normalize_live_video() -> None:
    observed_at = datetime(2026, 9, 8, tzinfo=timezone.utc)

    video = {
        "id": "abc123",
        "snippet": {
            "title": "Breaking News",
            "publishedAt": "2026-09-08T10:00:00Z",
            "liveBroadcastContent": "live",
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
    assert result.channel_id == "channel1"
    assert result.title == "Breaking News"
    assert result.published_at == "2026-09-08T10:00:00Z"

    assert result.view_count == 12345
    assert result.like_count == 678
    assert result.comment_count == 90

    assert result.concurrent_viewers == 4321
    assert result.is_live is True
    assert result.classification == "LIVE"

    assert result.live_started_at == "2026-09-08T10:01:00Z"
    assert result.live_ended_at is None


def test_normalize_regular_video() -> None:
    observed_at = datetime(2026, 9, 8, tzinfo=timezone.utc)

    video = {
        "id": "regular123",
        "snippet": {
            "title": "Regular News Video",
            "publishedAt": "2026-09-08T09:00:00Z",
            "liveBroadcastContent": "none",
        },
        "statistics": {
            "viewCount": "5000",
            "likeCount": "100",
            "commentCount": "20",
        },
        "contentDetails": {
            "duration": "PT10M30S",
        },
    }

    result = normalize_video(video, "channel1", observed_at)

    assert result.video_id == "regular123"
    assert result.channel_id == "channel1"
    assert result.title == "Regular News Video"

    assert result.view_count == 5000
    assert result.like_count == 100
    assert result.comment_count == 20

    assert result.concurrent_viewers is None
    assert result.is_live is False
    assert result.classification == "REGULAR_VIDEO"

    assert result.live_started_at is None
    assert result.live_ended_at is None


def test_normalize_upcoming_video() -> None:
    observed_at = datetime(2026, 9, 8, tzinfo=timezone.utc)

    video = {
        "id": "upcoming123",
        "snippet": {
            "title": "Upcoming Live Event",
            "publishedAt": "2026-09-08T15:00:00Z",
            "liveBroadcastContent": "upcoming",
        },
        "statistics": {
            "viewCount": "0",
            "likeCount": "0",
            "commentCount": "0",
        },
        "liveStreamingDetails": {},
    }

    result = normalize_video(video, "channel1", observed_at)

    assert result.video_id == "upcoming123"
    assert result.view_count == 0
    assert result.concurrent_viewers is None
    assert result.is_live is False
    assert result.classification == "UPCOMING"


def test_normalize_completed_live_video() -> None:
    observed_at = datetime(2026, 9, 8, tzinfo=timezone.utc)

    video = {
        "id": "completed123",
        "snippet": {
            "title": "Completed Live Broadcast",
            "publishedAt": "2026-09-08T10:00:00Z",
            "liveBroadcastContent": "none",
        },
        "statistics": {
            "viewCount": "25000",
            "likeCount": "500",
            "commentCount": "80",
        },
        "liveStreamingDetails": {
            "actualStartTime": "2026-09-08T10:01:00Z",
            "actualEndTime": "2026-09-08T11:01:00Z",
        },
    }

    result = normalize_video(video, "channel1", observed_at)

    assert result.video_id == "completed123"
    assert result.view_count == 25000
    assert result.concurrent_viewers is None
    assert result.is_live is False
    assert result.classification == "COMPLETED_LIVE"

    assert result.live_started_at == "2026-09-08T10:01:00Z"
    assert result.live_ended_at == "2026-09-08T11:01:00Z"


def test_normalize_unknown_video() -> None:
    observed_at = datetime(2026, 9, 8, tzinfo=timezone.utc)

    video = {
        "id": "unknown123",
        "snippet": {
            "title": "Unknown State",
            "publishedAt": "2026-09-08T10:00:00Z",
        },
        "statistics": {},
        "liveStreamingDetails": {},
    }

    result = normalize_video(video, "channel1", observed_at)

    assert result.video_id == "unknown123"
    assert result.is_live is False
    assert result.classification == "UNKNOWN"