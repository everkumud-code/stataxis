from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.media_intelligence import market_report
from collector.storage import Base, Channel, Observation, Video


def test_market_report_exposes_production_stx_from_persisted_history():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = Session(engine)
    channel = Channel(youtube_channel_id="a", name="Alpha", language="Hindi", region="India")
    session.add(channel)
    session.flush()
    video = Video(youtube_video_id="v", channel_id=channel.id, title="Live")
    session.add(video)
    session.flush()

    as_of = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    for index in range(6):
        session.add(
            Observation(
                video_id=video.id,
                channel_id=channel.id,
                observed_at=as_of - timedelta(minutes=50 - index * 10),
                view_count=1000 + index * 100,
                concurrent_viewers=200 + index * 10,
                like_count=10 + index,
                comment_count=2 + index,
                is_live=True,
                classification="LIVE",
            )
        )
    session.commit()

    payload = market_report(session, as_of=as_of, period="1h", language="Hindi", region="India")
    row = payload["channels"][0]
    assert row["stx"]["score"] is not None
    assert row["stx"]["confidence"] > 0
    assert "audience" in row["stx"]["signals"]
    assert payload["provenance"]["stx_source"] == "persisted_stataxis_observations"


def test_market_report_rows_include_display_stx_fields():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = Session(engine)
    channel = Channel(youtube_channel_id="display-a", name="Display Alpha", language="Hindi", region="India")
    session.add(channel)
    session.flush()
    video = Video(youtube_video_id="display-v", channel_id=channel.id, title="Display")
    session.add(video)
    session.flush()

    as_of = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    for index in range(2):
        session.add(
            Observation(
                video_id=video.id,
                channel_id=channel.id,
                observed_at=as_of - timedelta(minutes=10 - index * 10),
                view_count=1000 + index * 100,
                concurrent_viewers=200 + index * 10,
                like_count=10 + index,
                comment_count=2 + index,
                is_live=True,
                classification="LIVE",
            )
        )
    session.commit()

    row = market_report(session, as_of=as_of, period="1h", language="Hindi", region="India")["channels"][0]
    assert "display_score" in row["stx"]
    assert "preliminary" in row["stx"]
    assert row["stx"]["display_method"] == "50 + (score - 50) * confidence / 100"
