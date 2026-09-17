from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from api.insight_extensions import build_what_changed
from collector.storage import Channel, Observation, Video, create_database


def test_what_changed_is_evidence_first_and_deterministic():
    engine = create_database("sqlite:///:memory:")
    now = datetime.now(UTC).replace(microsecond=0)
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC_TEST", name="Test Channel", network="Test", language="English", region="India", active=True)
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="video-1", channel_id=channel.id, title="Strong growth and record profit")
        session.add(video)
        session.flush()
        session.add_all([
            Observation(video_id=video.id, channel_id=channel.id, observed_at=now - timedelta(hours=2), view_count=100, source="test", collector_version="test"),
            Observation(video_id=video.id, channel_id=channel.id, observed_at=now - timedelta(minutes=5), view_count=175, source="test", collector_version="test"),
        ])
        session.commit()

        payload = build_what_changed(session, channel_id=channel.id, hours=24, as_of=now)

    assert payload["changes"][0]["view_delta"] == 75
    assert payload["sentiment"]["method"] == "lexical_title_sentiment"
    assert payload["sentiment"]["label"] == "positive"
    assert payload["narrative"]["method"] == "title_term_frequency"
    assert payload["evidence"]["missing_values_are_not_zero_filled"] is True
    assert payload["evidence"]["causality_inferred"] is False
