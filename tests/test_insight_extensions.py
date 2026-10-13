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
            Observation(video_id=video.id, channel_id=channel.id, observed_at=now - timedelta(hours=26), view_count=100, source="test", collector_version="test"),
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


def test_tone_is_given_for_each_channel_and_a_switched_off_channel_is_left_out():
    engine = create_database("sqlite:///:memory:")
    now = datetime.now(UTC).replace(microsecond=0)
    with Session(engine) as session:
        made = {}
        for key, title, active in (("up", "Strong growth and record profit", True), ("down", "Crisis deepens after scandal and loss", True), ("off", "Great victory", False)):
            ch = Channel(youtube_channel_id=key, name=key.title() + " News", network="n", language="English", region="India", active=active)
            session.add(ch)
            session.flush()
            v = Video(youtube_video_id="v-" + key, channel_id=ch.id, title=title)
            session.add(v)
            session.flush()
            session.add_all([Observation(video_id=v.id, channel_id=ch.id, observed_at=now - timedelta(hours=h), view_count=100 + h, source="test", collector_version="test") for h in (20, 1)])
            made[key] = ch.id
        session.commit()
        payload = build_what_changed(session, hours=24, as_of=now)
    rows = {r["channel"]: r for r in payload["sentiment_by_channel"]}
    assert set(rows) == {"Up News", "Down News"}                                                   # Off News is switched off: not read, not listed
    assert rows["Up News"]["label"] == "positive" and rows["Down News"]["label"] == "negative"
    assert rows["Up News"]["titles_read"] == 1 and rows["Up News"]["top_terms"]
