"""Shorts are shown (scope=shorts) but never counted in analysis, rankings or STX."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.channel import channel_view_series
from api.media_intelligence import channel_media_intelligence, market_report
from collector.intelligence import process_persisted_observations
from collector.storage import Base, Channel, Observation, Video

AS_OF = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _seed():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    session = Session(engine)
    channel = Channel(youtube_channel_id="c", name="News", network="n", language="Hindi", region="India")
    session.add(channel)
    session.flush()
    long_form = Video(youtube_video_id="long", channel_id=channel.id, title="Full debate", published_at="2026-09-20T05:00:00Z")
    short = Video(youtube_video_id="short", channel_id=channel.id, title="Quick clip", published_at="2026-09-20T05:00:00Z")
    session.add_all([long_form, short])
    session.flush()
    first, last = AS_OF - timedelta(hours=2), AS_OF - timedelta(minutes=5)
    for video, classification, start, end in ((long_form, "REGULAR_VIDEO", 1_000, 1_500), (short, "SHORT", 5_000, 9_000)):
        for at, views in ((first, start), (last, end)):
            session.add(Observation(video_id=video.id, channel_id=channel.id, observed_at=at, view_count=views,
                                    like_count=1, comment_count=1, is_live=False, classification=classification))
    session.commit()
    return session, channel.id


def test_all_and_video_scopes_do_not_count_shorts():
    session, _ = _seed()
    for scope in ("all", "video"):
        payload = market_report(session, as_of=AS_OF, period="today", stream_scope=scope)
        assert payload["channels"][0]["view_delta"] == 500, scope
        assert payload["market"]["view_delta_total"] == 500, scope
        assert payload["counted_in_analysis"] is True


def test_shorts_scope_is_shown_but_has_no_stx_and_is_flagged_not_counted():
    session, _ = _seed()
    payload = market_report(session, as_of=AS_OF, period="today", stream_scope="shorts")
    row = payload["channels"][0]
    assert row["view_delta"] == 4_000
    assert row["stx"]["score"] is None
    assert "not counted" in row["stx"]["excluded_reason"]
    assert payload["counted_in_analysis"] is False
    assert "not counted" in payload["note"]


def test_channel_view_lists_show_shorts_only_in_the_shorts_scope():
    session, channel_id = _seed()
    counted = channel_media_intelligence(session, channel_id, as_of=AS_OF, period="today", stream_scope="all")
    assert [video["youtube_video_id"] for video in counted["content"]["top_videos"]] == ["long"]
    shown = channel_media_intelligence(session, channel_id, as_of=AS_OF, period="today", stream_scope="shorts")
    assert [video["youtube_video_id"] for video in shown["content"]["top_videos"]] == ["short"]
    assert shown["stx"]["score"] is None and shown["counted_in_analysis"] is False


def test_view_series_ignores_shorts():
    session, channel_id = _seed()
    series = channel_view_series(session, channel_id, as_of=AS_OF, days=1)
    assert max(point["value"] for point in series["points"]) == 1_500  # not 9,000 from the Short


def test_stx_intelligence_is_not_built_for_shorts():
    session, _ = _seed()
    result = process_persisted_observations(session)
    assert result.videos_processed == 1
