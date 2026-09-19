from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from collector.classification import VideoClassification
from collector.storage import Base, Channel, ChannelLanguageOverride, save_observations
from collector.youtube.collector import VideoObservation


def test_observations_are_append_only_and_duplicate_safe() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    observed_at = datetime.now(UTC)
    observation = VideoObservation(
        video_id="video1",
        channel_id="channel1",
        observed_at=observed_at,
        title="Test",
        published_at=None,
        view_count=100,
        like_count=10,
        comment_count=2,
        concurrent_viewers=25,
        is_live=True,
        classification=VideoClassification.LIVE.value,
        live_started_at=None,
        live_ended_at=None,
    )

    with Session(engine) as session:
        saved = save_observations(
            session=session,
            channel_name="Test Channel",
            channel_youtube_id="channel1",
            network="Test Network",
            language="Hindi",
            observations=[observation],
        )
        assert saved == 1

        # Replaying the exact same measurement must not create a second row.
        saved = save_observations(
            session=session,
            channel_name="Test Channel",
            channel_youtube_id="channel1",
            network="Test Network",
            language="Hindi",
            observations=[observation],
        )
        assert saved == 0

        # A genuinely new timestamp remains append-only.
        observation_2 = VideoObservation(
            video_id="video1",
            channel_id="channel1",
            observed_at=observed_at + timedelta(minutes=2),
            title="Test",
            published_at=None,
            view_count=150,
            like_count=12,
            comment_count=3,
            concurrent_viewers=35,
            is_live=True,
            classification=VideoClassification.LIVE.value,
            live_started_at=None,
            live_ended_at=None,
        )

        saved = save_observations(
            session=session,
            channel_name="Test Channel",
            channel_youtube_id="channel1",
            network="Test Network",
            language="Hindi",
            observations=[observation_2],
        )
        assert saved == 1

        rows = session.execute(
            Base.metadata.tables["stx_observations"].select()
        ).fetchall()

        assert len(rows) == 2
        assert rows[0].view_count == 100
        assert rows[1].view_count == 150


def test_save_observations_does_not_overwrite_curated_region_when_region_is_omitted() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    observation = VideoObservation(
        video_id="video-curated",
        channel_id="channel-curated",
        observed_at=datetime.now(UTC),
        title="Curated",
        published_at=None,
        view_count=100,
        like_count=10,
        comment_count=2,
        concurrent_viewers=25,
        is_live=True,
        classification=VideoClassification.LIVE.value,
        live_started_at=None,
        live_ended_at=None,
    )

    with Session(engine) as session:
        save_observations(
            session, "Curated Channel", "channel-curated", "Network", "Hindi", [observation],
            region="Jharkhand",
        )
        save_observations(
            session, "Collector Name", "channel-curated", "youtube", "unknown", [observation],
        )
        channel = session.query(Channel).filter_by(youtube_channel_id="channel-curated").one()
        assert channel.region == "Jharkhand"
        assert channel.language == "Hindi"

        override = ChannelLanguageOverride(channel_id=channel.id, language="Bhojpuri")
        session.add(override)
        session.commit()
        save_observations(
            session, "Collector Name", "channel-curated", "youtube", "English", [observation],
        )
        session.refresh(channel)
        assert channel.language == "Bhojpuri"


def _stub_database_dependencies(monkeypatch):
    from unittest.mock import MagicMock
    import collector.storage as storage

    calls = []
    engine = MagicMock()
    connection = MagicMock()
    engine.begin.return_value.__enter__.return_value = connection

    def fake_create_engine(*args, **kwargs):
        calls.append((args, kwargs))
        return engine

    monkeypatch.setattr(storage, "create_engine", fake_create_engine)
    monkeypatch.setattr(storage.Base.metadata, "create_all", lambda _engine: None)
    monkeypatch.setattr(storage, "inspect", lambda _connection: MagicMock(get_columns=lambda _table: [
        {"name": name} for name in (
            "approval_status", "full_name", "mobile", "organization",
            "purpose_of_use", "requested_plan",
        )
    ]))
    return storage, calls


def test_create_database_normalizes_postgres_urls(monkeypatch) -> None:
    storage, calls = _stub_database_dependencies(monkeypatch)

    storage.create_database("postgres://user:pass@host/db")
    storage.create_database("postgresql://user:pass@host/db")

    assert calls == [
        (("postgresql+psycopg://user:pass@host/db",), {"future": True, "pool_pre_ping": True, "pool_recycle": 240}),
        (("postgresql+psycopg://user:pass@host/db",), {"future": True, "pool_pre_ping": True, "pool_recycle": 240}),
    ]


def test_create_database_keeps_existing_postgres_driver_urls_unchanged(monkeypatch) -> None:
    storage, calls = _stub_database_dependencies(monkeypatch)

    storage.create_database("postgresql+psycopg://user:pass@host/db")

    assert calls == [(
        ("postgresql+psycopg://user:pass@host/db",),
        {"future": True, "pool_pre_ping": True, "pool_recycle": 240},
    )]


def test_create_database_keeps_sqlite_engine_options_unchanged(monkeypatch) -> None:
    storage, calls = _stub_database_dependencies(monkeypatch)

    storage.create_database("sqlite:///:memory:")

    assert calls == [(("sqlite:///:memory:",), {"future": True})]
