from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from collector import intelligence
from collector.intelligence import process_persisted_observations
from collector.storage import Channel, Observation, Video, create_database

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _video(session: Session, key: str, observed: list[datetime]) -> Video:
    channel = session.query(Channel).first() or Channel(youtube_channel_id="UC1", name="N")
    session.add(channel)
    session.flush()
    video = Video(youtube_video_id=key, channel_id=channel.id, title=key)
    session.add(video)
    session.flush()
    for moment in observed:
        session.add(Observation(video_id=video.id, channel_id=channel.id, observed_at=moment, view_count=10))
    session.flush()
    return video


def _spy(monkeypatch) -> list[int]:
    processed: list[int] = []
    monkeypatch.setattr(intelligence, "persist_video_intelligence", lambda session, video_id, limit=25: processed.append(video_id))
    return processed


def test_without_since_every_video_with_two_observations_is_processed(monkeypatch) -> None:
    processed = _spy(monkeypatch)
    with Session(create_database("sqlite:///:memory:")) as session:
        old = _video(session, "old", [NOW - timedelta(days=3), NOW - timedelta(days=2)])
        new = _video(session, "new", [NOW - timedelta(hours=2), NOW])
        session.commit()
        result = process_persisted_observations(session)
        assert sorted(processed) == sorted([old.id, new.id])
        assert result.snapshots_built == 2


def test_since_processes_only_videos_observed_in_this_pass(monkeypatch) -> None:
    processed = _spy(monkeypatch)
    with Session(create_database("sqlite:///:memory:")) as session:
        _video(session, "old", [NOW - timedelta(days=3), NOW - timedelta(days=2)])
        new = _video(session, "new", [NOW - timedelta(hours=2), NOW])
        session.commit()
        result = process_persisted_observations(session, since=NOW - timedelta(minutes=5))
        assert processed == [new.id]
        assert result.videos_processed == 1 and result.snapshots_built == 1


def test_videos_with_a_single_observation_are_skipped(monkeypatch) -> None:
    processed = _spy(monkeypatch)
    with Session(create_database("sqlite:///:memory:")) as session:
        _video(session, "single", [NOW])
        session.commit()
        result = process_persisted_observations(session, since=NOW - timedelta(minutes=5))
        assert processed == []
        assert (result.videos_processed, result.snapshots_built) == (1, 0)


def test_counts_use_grouped_queries_not_one_per_video(monkeypatch) -> None:
    _spy(monkeypatch)
    with Session(create_database("sqlite:///:memory:")) as session:
        for i in range(30):
            _video(session, f"v{i}", [NOW - timedelta(hours=1), NOW])
        session.commit()
        statements: list[str] = []
        from sqlalchemy import event
        event.listen(session.get_bind(), "before_cursor_execute", lambda c, cur, stmt, *a: statements.append(stmt))
        process_persisted_observations(session, since=NOW - timedelta(minutes=5))
        count_queries = [s for s in statements if "count(" in s.lower()]
        assert len(count_queries) == 1
