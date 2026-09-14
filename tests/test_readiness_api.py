from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.http import get_intelligence_readiness
from collector.storage import Base


def test_readiness_api_maps_validation_errors_without_mutation():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        status, payload = get_intelligence_readiness(session, min_snapshot_coverage=1.5)

    assert status == 400
    assert payload == {"error": "min_snapshot_coverage must be between 0 and 1"}
