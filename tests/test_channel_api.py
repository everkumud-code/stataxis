from datetime import datetime, timedelta, timezone
import json

from sqlalchemy.orm import Session

from api.channel import channel_intelligence_comparison
from api.http import get_channel_comparison
from collector.storage import Channel, Video, create_database
from metrics.persistence import IntelligenceSnapshotRecord


def _record(video_id, when, score, confidence, signals, contributions):
    return IntelligenceSnapshotRecord(
        video_id=video_id,
        generated_at=when,
        score=score,
        confidence=confidence,
        available_signals=signals,
        view_json="{}",
        contributions_json=json.dumps(contributions),
    )


def test_channel_comparison_uses_real_historical_snapshots_and_explains_change():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-history", name="History")
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="history-video", channel_id=channel.id, title="History")
        session.add(video)
        session.flush()

        as_of = datetime(2026, 9, 14, tzinfo=timezone.utc)
        session.add_all([
            _record(video.id, as_of - timedelta(days=365), 50, 0.5, 2, [{"name": "momentum", "contribution": 2}]),
            _record(video.id, as_of - timedelta(days=30), 70, 0.8, 3, [{"name": "momentum", "contribution": 5}]),
            _record(video.id, as_of, 80, 0.9, 4, [{"name": "momentum", "contribution": 8}, {"name": "acceleration", "contribution": 3}]),
        ])
        session.commit()

        result = channel_intelligence_comparison(session, channel.id, as_of=as_of)
        month = result["comparisons"]["last_1_month"]
        year = result["comparisons"]["last_1_year"]

        assert month["current"]["score"] == 80.0
        assert month["baseline"]["score"] == 70.0
        assert month["change"]["score_delta"] == 10.0
        assert month["change"]["sufficient_data"] is True
        assert month["contribution_changes"][0]["name"] == "momentum"
        assert year["baseline"]["score"] == 50.0


def test_channel_comparison_does_not_invent_missing_history():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-new", name="New")
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="new-video", channel_id=channel.id, title="New")
        session.add(video)
        session.flush()
        session.add(_record(video.id, datetime(2026, 9, 14, tzinfo=timezone.utc), 75, 0.8, 2, []))
        session.commit()

        result = channel_intelligence_comparison(session, channel.id, as_of=datetime(2026, 9, 14, tzinfo=timezone.utc))
        assert result["comparisons"]["last_3_weeks"]["baseline"] is None
        assert result["comparisons"]["last_3_weeks"]["change"]["sufficient_data"] is False


def test_channel_comparison_http_adapter_validates_ids_and_missing_channels():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        assert get_channel_comparison(session, 0)[0] == 400
        assert get_channel_comparison(session, 999)[0] == 404
