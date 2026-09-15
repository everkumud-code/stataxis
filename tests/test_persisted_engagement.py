from datetime import datetime, timezone

from sqlalchemy.orm import Session

from collector.storage import Channel, Observation, Video, create_database
from metrics.persisted import build_persisted_video_snapshot


def test_persisted_interactions_reach_stx_and_stat_axis_view():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-engagement", name="Engagement")
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="engagement-video", channel_id=channel.id, title="Measured")
        session.add(video)
        session.flush()
        session.add_all([
            Observation(
                video_id=video.id, channel_id=channel.id,
                observed_at=datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc),
                view_count=1000, like_count=100, comment_count=20,
            ),
            Observation(
                video_id=video.id, channel_id=channel.id,
                observed_at=datetime(2026, 9, 15, 0, 2, tzinfo=timezone.utc),
                view_count=1200, like_count=130, comment_count=30,
            ),
        ])
        session.commit()

        snapshot = build_persisted_video_snapshot(session, video.id)
        assert snapshot.intelligence.index.score is not None
        assert any(signal.name == "engagement" and signal.strength == 52.0 for signal in snapshot.intelligence.view.signals)
        assert "engagement" in snapshot.intelligence.index.component_scores
