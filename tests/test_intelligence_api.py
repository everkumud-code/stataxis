from datetime import UTC, datetime
import json

from sqlalchemy.orm import Session

from api.intelligence import latest_video_intelligence
from collector.storage import Channel, Video, create_database
from metrics.persistence import IntelligenceSnapshotRecord


def test_latest_video_intelligence_returns_newest_explainable_snapshot():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-api", name="API Test")
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="video-api", channel_id=channel.id, title="API Story")
        session.add(video)
        session.flush()
        base = dict(
            video_id=video.id,
            score=42.0,
            confidence=80.0,
            available_signals=3,
            view_json=json.dumps({
                "score": 42.0,
                "confidence": 80.0,
                "signals": [],
                "data": ["Observed audience movement."],
                "analysis": ["Momentum is positive."],
                "view": "The available evidence supports a positive directional signal.",
                "measurement_provenance": {"observation_count": 3},
            }),
            contributions_json=json.dumps([{"name": "momentum", "value": 0.5, "contribution": 10.0, "share_of_score": 23.8}]),
        )
        session.add(IntelligenceSnapshotRecord(generated_at=datetime(2026, 9, 14, 12, tzinfo=UTC), **base))
        session.add(IntelligenceSnapshotRecord(generated_at=datetime(2026, 9, 14, 13, tzinfo=UTC), score=55.0, **{k: v for k, v in base.items() if k != "score"}))
        session.commit()

        result = latest_video_intelligence(session, video.id)
        assert result["score"] == 55.0
        assert result["youtube_video_id"] == "video-api"
        assert result["stx_index"] == {"score": 55.0, "confidence": 80.0, "available_signals": 3}
        assert result["data"] == ["Observed audience movement."]
        assert result["analysis"] == ["Momentum is positive."]
        assert result["view"] == "The available evidence supports a positive directional signal."
        assert result["signal_contributions"][0]["name"] == "momentum"
        assert result["measurement_provenance"]["observation_count"] == 3


def test_latest_video_intelligence_returns_none_for_unknown_video():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        assert latest_video_intelligence(session, 999) is None


def test_latest_video_intelligence_falls_back_for_legacy_view_payload():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-legacy", name="Legacy")
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="video-legacy", channel_id=channel.id, title="Legacy Story")
        session.add(video)
        session.flush()
        session.add(IntelligenceSnapshotRecord(
            video_id=video.id,
            generated_at=datetime(2026, 9, 14, 14, tzinfo=UTC),
            score=50.0,
            confidence=50.0,
            available_signals=2,
            view_json=json.dumps({"score": 50.0, "confidence": 50.0, "signals": []}),
            contributions_json=json.dumps([]),
        ))
        session.commit()

        result = latest_video_intelligence(session, video.id)
        assert result["stx_index"]["score"] == 50.0
        assert result["data"] == []
        assert result["analysis"] == []
        assert result["view"] == "No persisted StatAxis View available."
