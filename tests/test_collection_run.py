from sqlalchemy.orm import Session

from collector.run import run_collection_pass
from collector.storage import CollectionRun, Observation, create_database
from collector.youtube.collector import ChannelTarget


class FakeClient:
    def __init__(self, fail_channel_id: str | None = None):
        self.fail_channel_id = fail_channel_id

    def get_channel(self, channel_id: str):
        if channel_id == self.fail_channel_id:
            raise RuntimeError("upstream unavailable")
        return {"contentDetails": {"relatedPlaylists": {"uploads": f"uploads-{channel_id}"}}}

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


def test_collection_pass_records_partial_failure_without_stopping_cycle():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        result = run_collection_pass(
            session,
            FakeClient(fail_channel_id="UC-bad"),
            [ChannelTarget("UC-bad", "Broken"), ChannelTarget("UC-good", "Healthy")],
            max_videos=1,
        )

        run = session.get(CollectionRun, result.run_id)
        assert run is not None
        assert run.status == "partial"
        assert run.finished_at is not None
        assert run.error_message == "Broken: upstream unavailable"
        assert run.channels_attempted == 2
        assert run.videos_observed == 1
        assert session.query(Observation).count() == 1
