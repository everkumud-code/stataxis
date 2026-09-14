import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from collector.storage import Channel, Observation, Video, create_database
from metrics.persistence import persist_video_intelligence


def test_persisted_snapshot_includes_measurement_provenance():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC-prov", name="Provenance")
        session.add(channel)
        session.flush()
        video = Video(youtube_video_id="vid-prov", channel_id=channel.id, title="Measured")
        session.add(video)
        session.flush()
        t0 = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 9, 14, 10, 5, tzinfo=timezone.utc)
        session.add_all([
            Observation(video_id=video.id, channel_id=channel.id, observed_at=t0,
                        view_count=100, concurrent_viewers=10),
            Observation(video_id=video.id, channel_id=channel.id, observed_at=t1,
                        view_count=180, concurrent_viewers=25),
        ])
        session.commit()

        record = persist_video_intelligence(session, video.id)
        payload = json.loads(record.view_json)
        provenance = payload["measurement_provenance"]

        assert provenance["observation_count"] == 2
        assert provenance["oldest_observation"] == t0.isoformat()
        assert provenance["newest_observation"] == t1.isoformat()
        assert provenance["window_seconds"] == 300.0
        assert record.score is not None
        assert record.available_signals >= 2
