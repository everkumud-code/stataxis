from datetime import datetime, timezone

from sqlalchemy.orm import Session

from api.channel import channel_intelligence_overview
from collector.storage import Channel, Observation, Video, create_database
from metrics.persistence import IntelligenceSnapshotRecord


def test_channel_overview_uses_latest_snapshot_and_ranks_by_score():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-test", name="Test")
        session.add(channel)
        session.flush()
        first = Video(youtube_video_id="v1", channel_id=channel.id, title="One")
        second = Video(youtube_video_id="v2", channel_id=channel.id, title="Two")
        session.add_all([first, second])
        session.flush()
        now = datetime(2026, 9, 14, tzinfo=timezone.utc)
        session.add_all([
            IntelligenceSnapshotRecord(video_id=first.id, generated_at=now, score=40, confidence=0.8, available_signals=2, view_json="{}", contributions_json="[]"),
            IntelligenceSnapshotRecord(video_id=first.id, generated_at=now.replace(minute=1), score=80, confidence=0.7, available_signals=3, view_json="{}", contributions_json="[]"),
            IntelligenceSnapshotRecord(video_id=second.id, generated_at=now, score=60, confidence=0.9, available_signals=2, view_json="{}", contributions_json="[]"),
        ])
        session.commit()
        result = channel_intelligence_overview(session, channel.id)
        assert [item["score"] for item in result["videos"]] == [80, 60]
        assert result["videos"][0]["available_signals"] == 3


def test_channel_overview_returns_none_for_missing_channel():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        assert channel_intelligence_overview(session, 999) is None
