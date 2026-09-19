from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from api.live_monitor import language_group, live_audience_window
from collector.storage import Channel, Observation, Video, create_database


def test_language_group_maps_market_buckets():
    assert language_group("hi-IN") == "Hindi"
    assert language_group("en-US") == "English"
    assert language_group("bn-IN") == "Regional"
    assert language_group("unknown") == "Unknown"


def test_live_audience_window_returns_exact_observed_seconds_without_interpolation():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        hindi = Channel(youtube_channel_id="UC-hi", name="Hindi News", language="hi-IN", active=True)
        english = Channel(youtube_channel_id="UC-en", name="English News", language="en-US", active=True)
        regional = Channel(youtube_channel_id="UC-bn", name="Regional News", language="bn-IN", active=True)
        session.add_all([hindi, english, regional])
        session.flush()
        videos = [
            Video(youtube_video_id="video-hi", channel_id=hindi.id, title="Hindi"),
            Video(youtube_video_id="video-en", channel_id=english.id, title="English"),
            Video(youtube_video_id="video-bn", channel_id=regional.id, title="Regional"),
        ]
        session.add_all(videos)
        session.flush()
        base = datetime(2026, 9, 16, 9, 0, 0, tzinfo=timezone.utc)
        session.add_all([
            Observation(video_id=videos[0].id, channel_id=hindi.id, observed_at=base, concurrent_viewers=100, is_live=True),
            Observation(video_id=videos[1].id, channel_id=english.id, observed_at=base, concurrent_viewers=50, is_live=True),
            Observation(video_id=videos[2].id, channel_id=regional.id, observed_at=base, concurrent_viewers=25, is_live=True),
            Observation(video_id=videos[0].id, channel_id=hindi.id, observed_at=base + timedelta(seconds=2), concurrent_viewers=140, is_live=True),
            Observation(video_id=videos[1].id, channel_id=english.id, observed_at=base + timedelta(seconds=2), concurrent_viewers=70, is_live=True),
        ])
        session.commit()

        payload = live_audience_window(session, start_at=base, end_at=base + timedelta(seconds=4))

        assert [point["observed_at"] for point in payload["timeline"]] == [base.isoformat(), (base + timedelta(seconds=2)).isoformat()]
        assert payload["overall"]["peak_concurrent"] == 210
        assert payload["overall"]["observed_seconds"] == 2
        assert payload["languages"]["Hindi"]["current_concurrent"] == 140
        assert payload["languages"]["Hindi"]["peak_concurrent"] == 140
        assert payload["languages"]["English"]["current_concurrent"] == 70
        assert payload["languages"]["Regional"]["peak_concurrent"] == 25
        assert payload["interpolation"] is False


def test_live_audience_window_buckets_long_windows_and_preserves_raw_peak():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-long", name="Long Live", language="hi-IN", active=True)
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="video-long", channel_id=channel.id, title="Long")
        session.add(video)
        session.flush()
        base = datetime(2026, 9, 16, 9, 0, 0, tzinfo=timezone.utc)
        session.add_all([
            Observation(video_id=video.id, channel_id=channel.id, observed_at=base, concurrent_viewers=100, is_live=True),
            Observation(video_id=video.id, channel_id=channel.id, observed_at=base + timedelta(seconds=20), concurrent_viewers=300, is_live=True),
            Observation(video_id=video.id, channel_id=channel.id, observed_at=base + timedelta(seconds=40), concurrent_viewers=200, is_live=True),
            Observation(video_id=video.id, channel_id=channel.id, observed_at=base + timedelta(minutes=1), concurrent_viewers=50, is_live=True),
        ])
        session.commit()

        payload = live_audience_window(
            session,
            start_at=base,
            end_at=base + timedelta(hours=3),
        )

        assert payload["sample_resolution"] == "1-minute buckets"
        assert len(payload["timeline"]) == 2
        assert payload["timeline"][0]["Hindi"] == 200
        assert payload["timeline"][0]["total_concurrent"] == 200
        assert payload["overall"]["peak_concurrent"] == 300
