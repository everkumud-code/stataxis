from datetime import datetime, timezone

from sqlalchemy.orm import Session

from api.rankings import top_channel_videos
from collector.storage import Channel, Video, create_database
from metrics.persistence import IntelligenceSnapshotRecord


def test_top_channel_videos_ranks_latest_snapshot_without_mutation():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-rank", name="Rank")
        session.add(channel)
        session.flush()
        videos = [Video(youtube_video_id=f"v{i}", channel_id=channel.id, title=f"Video {i}") for i in range(3)]
        session.add_all(videos)
        session.flush()
        for i, (score, confidence) in enumerate(((41.0, .7), (88.0, .8), (63.0, .9))):
            session.add(IntelligenceSnapshotRecord(
                video_id=videos[i].id,
                score=score,
                confidence=confidence,
                available_signals=3,
                view_json="{}",
                contributions_json="[]",
                generated_at=datetime(2026, 9, 14, 1, i, tzinfo=timezone.utc),
            ))
        session.commit()
        before = session.query(IntelligenceSnapshotRecord).count()
        result = top_channel_videos(session, channel.id, limit=2)
        assert [item["score"] for item in result] == [88.0, 63.0]
        assert session.query(IntelligenceSnapshotRecord).count() == before


def test_top_channel_videos_empty_safe():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        assert top_channel_videos(session, 999) == []
        assert top_channel_videos(session, 1, 0) == []
