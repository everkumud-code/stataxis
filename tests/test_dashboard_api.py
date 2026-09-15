from datetime import datetime, timezone

from sqlalchemy.orm import Session

from collector.storage import Channel, Observation, Video, create_database
from collector.intelligence import persist_intelligence_snapshot
from dashboard.api import get_intelligence


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
