from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from api.signals import channel_signals
from collector.storage import Channel, Observation, create_database


def test_channel_signals_calculates_recent_velocity_and_momentum():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-signals", name="Signals")
        session.add(channel)
        session.flush()
        base = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
        session.add_all([
            Observation(video_id=1, channel_id=channel.id, observed_at=base, view_count=1000, concurrent_viewers=100, is_live=True),
            Observation(video_id=1, channel_id=channel.id, observed_at=base + timedelta(minutes=10), view_count=1600, concurrent_viewers=130, is_live=True),
            Observation(video_id=1, channel_id=channel.id, observed_at=base + timedelta(minutes=20), view_count=2200, concurrent_viewers=160, is_live=True),
        ])
        session.commit()

        result = channel_signals(session, channel.id, window_hours=24)
        assert result["observation_count"] == 3
        assert result["average_view_velocity_per_minute"] == 60.0
        assert result["average_audience_momentum_per_minute"] == 3.0
        assert result["momentum_direction"] == "positive"
        assert result["live_observation_count"] == 3


def test_channel_signals_returns_insufficient_data_without_concurrent_viewers():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-no-live", name="No Live")
        session.add(channel)
        session.flush()
        base = datetime.now(timezone.utc)
        session.add_all([
            Observation(video_id=1, channel_id=channel.id, observed_at=base - timedelta(minutes=10), view_count=1000),
            Observation(video_id=1, channel_id=channel.id, observed_at=base, view_count=1200),
        ])
        session.commit()
        result = channel_signals(session, channel.id)
        assert result["view_velocity_per_minute"] is not None
        assert result["audience_momentum_per_minute"] is None
        assert result["momentum_direction"] == "insufficient_data"
