from sqlalchemy.orm import Session

from collector.storage import create_database
from metrics.persisted import build_persisted_video_snapshot
from tests.test_persisted_pipeline import _seed


def test_persisted_snapshot_exposes_consistency_signal_and_explanation():
    engine = create_database("sqlite:///:memory:")
    with Session(engine) as session:
        video_id = _seed(session)
        result = build_persisted_video_snapshot(session, video_id)
        assert result.intelligence.index.available_signals == 5
        assert result.intelligence.index.component_scores["consistency"] > 0
        assert any(item.name == "consistency" for item in result.contributions)
        assert result.intelligence.view.confidence == result.intelligence.index.confidence
