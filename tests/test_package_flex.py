from api.package_config import list_package_slots, update_package_slot
from collector.storage import create_database
from sqlalchemy.orm import Session


def test_package_configuration_round_trips_all_commercial_fields(tmp_path):
    engine = create_database(f"sqlite:///{tmp_path / 'packages.db'}")
    with Session(engine) as session:
        update_package_slot(session, 5, {"name": "Launch", "criteria": ["10 channels"], "privileges": ["CSV export", "STX"], "amount": 1999, "currency": "INR", "duration_value": 30, "duration_unit": "day", "active": True})
        row = list_package_slots(session)[0]
        assert row["name"] == "Launch"
        assert row["criteria"] == ["10 channels"]
        assert row["privileges"] == ["CSV export", "STX"]
        assert row["amount"] == 1999.0
        assert row["duration_value"] == 30 and row["duration_unit"] == "day"
        assert row["active"] is True
