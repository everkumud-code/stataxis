from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.live_monitor import live_audience_window
from collector.storage import Base, Channel, Observation, Video


def test_live_audience_current_is_latest_per_channel_not_last_bucket():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        channel_a = Channel(youtube_channel_id="a", name="A", network="n", language="Hindi", region="India", active=True)
        channel_b = Channel(youtube_channel_id="b", name="B", network="n", language="English", region="India", active=True)
        session.add_all([channel_a, channel_b])
        session.flush()
        video_a = Video(youtube_video_id="va", channel_id=channel_a.id, title="A")
        video_b = Video(youtube_video_id="vb", channel_id=channel_b.id, title="B")
        session.add_all([video_a, video_b])
        session.flush()
        start = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
        session.add_all([
            Observation(video_id=video_a.id, channel_id=channel_a.id, observed_at=start, view_count=1, concurrent_viewers=100, is_live=True, source="test"),
            Observation(video_id=video_b.id, channel_id=channel_b.id, observed_at=start + timedelta(seconds=1), view_count=1, concurrent_viewers=200, is_live=True, source="test"),
            Observation(video_id=video_a.id, channel_id=channel_a.id, observed_at=start + timedelta(seconds=2), view_count=1, concurrent_viewers=150, is_live=True, source="test"),
        ])
        session.commit()

        payload = live_audience_window(session, start_at=start, end_at=start + timedelta(seconds=5))
        assert payload["overall"]["current_concurrent"] == 350
        assert payload["overall"]["current_definition"].startswith("sum of each active channel")
        assert payload["interpolation"] is False
