from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.media_intelligence import channel_media_intelligence, market_report
from collector.storage import Base, Channel, Observation, Video


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed(session: Session):
    a = Channel(youtube_channel_id="a", name="Alpha", language="Hindi", region="India")
    b = Channel(youtube_channel_id="b", name="Beta", language="Hindi", region="India")
    session.add_all([a, b])
    session.flush()
    va = Video(youtube_video_id="va", channel_id=a.id, title="Alpha live", published_at="2026-09-10T09:00:00+00:00")
    vb = Video(youtube_video_id="vb", channel_id=b.id, title="Beta live", published_at="2026-09-10T09:00:00+00:00")
    session.add_all([va, vb])
    session.flush()
    base = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    session.add_all([
        Observation(video_id=va.id, channel_id=a.id, observed_at=base - timedelta(hours=1), view_count=1000, like_count=10, comment_count=2, concurrent_viewers=100, is_live=True, classification="LIVE"),
        Observation(video_id=va.id, channel_id=a.id, observed_at=base, view_count=1600, like_count=16, comment_count=5, concurrent_viewers=180, is_live=True, classification="LIVE"),
        Observation(video_id=vb.id, channel_id=b.id, observed_at=base - timedelta(hours=1), view_count=2000, like_count=20, comment_count=3, concurrent_viewers=80, is_live=True, classification="LIVE"),
        Observation(video_id=vb.id, channel_id=b.id, observed_at=base, view_count=2200, like_count=22, comment_count=4, concurrent_viewers=120, is_live=True, classification="LIVE"),
    ])
    session.commit()
    return base, a.id, b.id


def test_market_report_calculates_channel_metrics_and_share():
    session = _session()
    as_of, alpha_id, beta_id = _seed(session)
    payload = market_report(session, as_of=as_of, period="1h", language="Hindi", region="India")

    assert payload["market"]["channel_count"] == 2
    assert payload["market"]["view_delta_total"] == 800
    assert payload["channels"][0]["channel_id"] == alpha_id
    assert payload["channels"][0]["view_delta"] == 600
    assert payload["channels"][0]["average_concurrent"] == 140
    assert payload["channels"][0]["peak_concurrent"] == 180
    assert payload["channels"][0]["rank"] == 1
    assert payload["channels"][0]["rank_change"] is None
    assert payload["channels"][1]["channel_id"] == beta_id


def test_channel_media_intelligence_exposes_content_and_provenance():
    session = _session()
    as_of, alpha_id, _ = _seed(session)
    payload = channel_media_intelligence(session, alpha_id, as_of=as_of, period="1h")

    assert payload is not None
    assert payload["audience"]["current_concurrent"] == 180
    assert payload["momentum"]["view_delta"] == 600
    assert payload["momentum"]["view_velocity_per_minute"] == 10
    assert payload["content"]["videos_observed"] == 1
    assert payload["content"]["top_videos"][0]["view_delta"] == 600
    assert payload["provenance"]["missing_values_are_not_zero_filled"] is True


def test_stream_scope_can_isolate_live_observations():
    session = _session()
    as_of, alpha_id, _ = _seed(session)
    video_id = session.query(Video).filter_by(youtube_video_id="va").one().id
    session.add(Observation(
        video_id=video_id,
        channel_id=alpha_id,
        observed_at=as_of - timedelta(minutes=30),
        view_count=1300,
        like_count=13,
        comment_count=4,
        concurrent_viewers=None,
        is_live=False,
        classification="REGULAR_VIDEO",
    ))
    session.commit()
    payload = channel_media_intelligence(session, alpha_id, as_of=as_of, period="1h", stream_scope="live")
    assert payload is not None
    assert payload["audience"]["peak_concurrent"] == 180
    assert payload["momentum"]["view_delta"] == 600


def test_channel_media_intelligence_stx_includes_display_fields():
    session = _session()
    as_of, alpha_id, _ = _seed(session)
    payload = channel_media_intelligence(session, alpha_id, as_of=as_of, period="1h")

    assert payload is not None
    assert "display_score" in payload["stx"]
    assert "preliminary" in payload["stx"]
    assert payload["stx"]["display_method"] == "50 + (score - 50) * confidence / 100"
