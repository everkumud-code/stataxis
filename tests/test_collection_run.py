from datetime import UTC, datetime

from sqlalchemy.orm import Session

from collector.run import run_collection_pass
from collector.storage import Base, Channel, CollectionRun, Observation, create_database
from collector.youtube.collector import ChannelTarget


class FakeClient:
    def __init__(self, fail_channel_id: str | None = None, missing_ids: set[str] | None = None):
        self.fail_channel_id = fail_channel_id
        self.missing_ids = missing_ids or set()

    def get_channels(self, channel_ids: list[str]):
        if self.fail_channel_id in channel_ids:
            raise RuntimeError("upstream unavailable")
        return [
            {"id": channel_id, "contentDetails": {"relatedPlaylists": {"uploads": f"uploads-{channel_id}"}}}
            for channel_id in channel_ids
            if channel_id not in self.missing_ids
        ]

    def list_uploads(self, uploads_id: str, max_results: int):
        channel_id = uploads_id.removeprefix("uploads-")
        return {"items": [{"contentDetails": {"videoId": f"video-{channel_id}"}}]}

    def get_videos(self, video_ids: list[str]):
        return [
            {
                "id": video_id,
                "snippet": {"title": "Test story", "publishedAt": "2026-09-14T00:00:00Z"},
                "statistics": {"viewCount": "250"},
            }
            for video_id in video_ids
        ]


def test_collection_pass_records_success_and_intelligence():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        result = run_collection_pass(
            session,
            FakeClient(),
            [ChannelTarget("UC-test", "Test")],
            max_videos=1,
        )

        run = session.get(CollectionRun, result.run_id)
        assert run is not None
        assert run.status == "success"
        assert run.finished_at is not None
        assert run.channels_attempted == 1
        assert run.videos_observed == 1
        assert result.intelligence.videos_processed == 1
        assert session.query(Observation).count() == 1


def test_collection_pass_records_failure_without_erasing_run():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        try:
            run_collection_pass(
                session,
                FakeClient(fail_channel_id="UC-bad"),
                [ChannelTarget("UC-bad", "Broken")],
                max_videos=1,
            )
        except RuntimeError as exc:
            assert str(exc) == "upstream unavailable"
        else:
            raise AssertionError("expected collection failure")

        run = session.query(CollectionRun).one()
        assert run.status == "failed"
        assert run.finished_at is not None
        assert run.error_message == "upstream unavailable"
        assert run.channels_attempted == 1
        assert run.videos_observed == 0


def test_pass_with_one_missing_channel_is_partial_not_failed():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        result = run_collection_pass(
            session,
            FakeClient(missing_ids={"UC-gone"}),
            [ChannelTarget("UC-ok", "Working"), ChannelTarget("UC-gone", "Deleted")],
            max_videos=1,
        )
        run = session.query(CollectionRun).one()
        assert run.status == "partial"
        assert "Deleted [UC-gone: channel not found]" in run.error_message
        assert result.videos_observed == 1


def test_pass_where_no_channel_can_be_collected_fails():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        try:
            run_collection_pass(session, FakeClient(missing_ids={"UC-gone"}), [ChannelTarget("UC-gone", "Deleted")], max_videos=1)
        except RuntimeError as exc:
            assert "no channel could be collected" in str(exc)
        else:
            raise AssertionError("expected failure")
        assert session.query(CollectionRun).one().status == "failed"
