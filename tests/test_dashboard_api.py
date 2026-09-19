import json
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import event
from sqlalchemy.orm import Session

from collector.storage import Channel, ChannelStats, Observation, Video, create_database
from collector.intelligence import persist_intelligence_snapshot
from dashboard.api import get_intelligence
from api.auth_guard import protect_application
from api.dashboard_data import channel_stx_trend
from api.http import wsgi_application
from metrics.persistence import IntelligenceSnapshotRecord


def test_api_returns_json_serializable_intelligence():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-api", name="API")
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="api-video", channel_id=channel.id, title="API video")
        session.add(video)
        session.flush()
        session.add_all([
            Observation(video_id=video.id, channel_id=channel.id,
                        observed_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
                        view_count=100, concurrent_viewers=10, classification="VOD"),
            Observation(video_id=video.id, channel_id=channel.id,
                        observed_at=datetime(2026, 9, 14, 0, 2, tzinfo=timezone.utc),
                        view_count=180, concurrent_viewers=30, classification="VOD"),
        ])
        session.commit()
        persist_intelligence_snapshot(session, video.id)
        payload = get_intelligence(session, video.id)

        assert payload is not None
        assert payload["score"] is not None
        assert payload["video_id"] == video.id
        assert isinstance(payload["signals"], (list, tuple))
        assert payload["stat_axis_view"]["score"] == payload["score"]
        provenance = payload["measurement_provenance"]
        assert provenance["observation_count"] == 2
        assert provenance["schema_version"] == 1
        assert provenance["oldest_observation"] == "2026-09-14T00:00:00+00:00"
        assert provenance["newest_observation"] == "2026-09-14T00:02:00+00:00"
        assert provenance["window_seconds"] == 120.0
        assert provenance["signals"]["growth"]["source"] == "persisted_observations"
        assert provenance["signals"]["growth"]["observation_count"] == 2
        assert provenance["signals"]["growth"]["derived"] is True


def test_api_is_read_only_and_missing_safe():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        assert get_intelligence(session, 999999) is None


def _request(app, path, query=""):
    captured = {}
    body = app(
        {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": query},
        lambda status, headers: captured.update(status=status, headers=headers),
    )
    return captured["status"], json.loads(body[0])


def _seed_dashboard():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        hindi = Channel(youtube_channel_id="UC-dashboard", name="Dashboard", language="Hindi", active=True)
        peer = Channel(youtube_channel_id="UC-peer", name="Peer", language="Hindi", active=True)
        session.add_all([hindi, peer])
        session.flush()
        now = datetime(2026, 9, 19, 12, tzinfo=UTC)
        session.add_all([
            ChannelStats(channel_id=hindi.id, observed_at=now - timedelta(days=30), subscribers=900, total_views=9000, video_count=9),
            ChannelStats(channel_id=hindi.id, observed_at=now, subscribers=1000, total_views=12000, video_count=12),
            ChannelStats(channel_id=peer.id, observed_at=now, subscribers=1500, total_views=20000, video_count=20),
        ])
        video = Video(
            youtube_video_id="video-dashboard-api",
            channel_id=hindi.id,
            title="Election update",
            published_at=(now - timedelta(days=2)).isoformat(),
            topic="Politics",
        )
        session.add(video)
        session.flush()
        session.add_all([
            Observation(video_id=video.id, channel_id=hindi.id, observed_at=now - timedelta(hours=2), view_count=1000, like_count=40, comment_count=10),
            Observation(video_id=video.id, channel_id=hindi.id, observed_at=now, view_count=1200, like_count=50, comment_count=15),
        ])
        session.add(IntelligenceSnapshotRecord(
            video_id=video.id, generated_at=now, score=72.5, confidence=0.9,
            available_signals=3, view_json="{}", contributions_json="[]",
        ))
        session.commit()
        channel_id = hindi.id
    return engine, channel_id


def test_dashboard_endpoints_require_auth():
    engine, channel_id = _seed_dashboard()
    app = protect_application(wsgi_application(lambda: Session(engine)))
    status, payload = _request(app, f"/api/v1/channels/{channel_id}/overview")
    assert status == "401 Unauthorized"
    assert payload == {"error": "authentication required"}


def test_channel_overview_wsgi_returns_shape_and_rank():
    engine, channel_id = _seed_dashboard()
    status, payload = _request(wsgi_application(lambda: Session(engine)), f"/api/v1/channels/{channel_id}/overview")
    assert status == "200 OK"
    assert payload["subscribers"]["value"] == 1000
    assert payload["subscribers_change_30d"]["value"] == 100
    assert payload["total_views_change_30d"]["value"] == 3000
    assert payload["uploads_in_window"]["value"] == 3
    assert payload["subscribers_rank_in_language"]["value"] == 2
    assert payload["rank_basis"] == "subscribers"
    assert payload["uploads_in_window"]["value"] == 3
    assert payload["observed_uploads_in_window"]["value"] == 1
    assert payload["observed_uploads_in_window"]["reason"] == "collection only tracks the latest videos"


def test_channel_overview_wsgi_returns_null_reason_without_history():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-empty", name="Empty", language="Hindi", active=True)
        session.add(channel)
        session.commit()
        channel_id = channel.id
    status, payload = _request(wsgi_application(lambda: Session(engine)), f"/api/v1/channels/{channel_id}/overview")
    assert status == "200 OK"
    assert payload["subscribers"]["value"] is None
    assert payload["subscribers"]["reason"] == "no stored channel statistics"
    assert payload["subscribers_change_30d"]["value"] is None


def test_stx_trend_wsgi_has_one_value_per_day_and_nulls_missing_days():
    engine, channel_id = _seed_dashboard()
    status, payload = _request(wsgi_application(lambda: Session(engine)), f"/api/v1/channels/{channel_id}/stx-trend", "days=3")
    assert status == "200 OK"
    assert len(payload["timeline"]) == 3
    assert payload["timeline"][-1]["stx"] is not None
    assert payload["timeline"][0]["stx"] is None
    assert payload["timeline"][0]["reason"] == "insufficient stored observations for daily STX"


def test_market_topics_wsgi_returns_distribution_shape():
    engine, _channel_id = _seed_dashboard()
    status, payload = _request(wsgi_application(lambda: Session(engine)), "/api/v1/markets/topics", "period=30d")
    assert status == "200 OK"
    assert payload["channels"][0]["topics"]["Politics"]["count"] == 1


def test_channel_stx_trend_uses_small_number_of_sql_statements_for_30_days():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-trend-bulk", name="Bulk", language="Hindi")
        session.add(channel)
        session.flush()
        start = datetime(2026, 8, 21, tzinfo=UTC)
        for video_number in range(5):
            video = Video(
                youtube_video_id=f"trend-video-{video_number}",
                channel_id=channel.id,
                title=f"Video {video_number}",
            )
            session.add(video)
            session.flush()
            for day in range(30):
                day_start = start + timedelta(days=day)
                session.add_all([
                    Observation(
                        video_id=video.id, channel_id=channel.id,
                        observed_at=day_start + timedelta(hours=1),
                        view_count=1000 + day * 10 + video_number,
                        concurrent_viewers=100 + day,
                        like_count=10, comment_count=2, classification="VOD",
                    ),
                    Observation(
                        video_id=video.id, channel_id=channel.id,
                        observed_at=day_start + timedelta(hours=23),
                        view_count=1100 + day * 10 + video_number,
                        concurrent_viewers=120 + day,
                        like_count=12, comment_count=3, classification="VOD",
                    ),
                ])
        session.commit()
        statements = []
        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(engine, "before_cursor_execute", before_cursor_execute)
        try:
            payload = channel_stx_trend(
                session,
                channel.id,
                days=30,
                as_of=start + timedelta(days=29, hours=23, minutes=59),
            )
        finally:
            event.remove(engine, "before_cursor_execute", before_cursor_execute)
        assert len(payload["timeline"]) == 30
        assert payload["definition"].startswith("Daily STX uses each day's trailing 24-hour window")
        assert sum("SELECT" in statement.upper() for statement in statements) <= 5


def test_channel_stx_trend_rejects_more_than_90_days():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-trend-cap", name="Cap")
        session.add(channel)
        session.commit()
        try:
            channel_stx_trend(session, channel.id, days=91)
        except ValueError as exc:
            assert str(exc) == "days must be between 1 and 90"
        else:
            raise AssertionError("expected 90-day cap")
