from api.package_config import list_package_slots, update_package_slot
from collector.storage import create_database
from sqlalchemy.orm import Session


def test_reserved_slots_are_created_and_empty(tmp_path):
    engine = create_database(f"sqlite:///{tmp_path / 'packages.db'}")
    with Session(engine) as session:
        rows = list_package_slots(session)
    assert [row["slot"] for row in rows] == list(range(5, 41))
    assert all(row["name"] is None and row["criteria"] == [] and row["privileges"] == [] and row["amount"] is None and row["duration_value"] is None and not row["active"] for row in rows)


def test_package_slot_name_criteria_privileges_price_and_duration_are_editable(tmp_path):
    engine = create_database(f"sqlite:///{tmp_path / 'packages.db'}")
    with Session(engine) as session:
        saved = update_package_slot(session, 12, {"name": "Newsroom Pro", "criteria": ["12 channels", "Daily reports"], "privileges": ["Export reports", "STX intelligence"], "amount": "4999.00", "currency": "INR", "duration_value": 1, "duration_unit": "month", "active": True})
        assert saved["slot"] == 12
        assert saved["name"] == "Newsroom Pro"
        assert saved["criteria"] == ["12 channels", "Daily reports"]
        assert saved["privileges"] == ["Export reports", "STX intelligence"]
        assert saved["amount"] == 4999.0 and saved["currency"] == "INR"
        assert saved["duration_value"] == 1 and saved["duration_unit"] == "month" and saved["active"] is True
        again = update_package_slot(session, 12, {"name": "Newsroom Pro Plus", "criteria": ["40 channels"], "privileges": ["All exports"], "amount": "7999", "duration_value": 1, "duration_unit": "year", "active": False})
        assert again["name"] == "Newsroom Pro Plus"
        assert again["criteria"] == ["40 channels"] and again["privileges"] == ["All exports"]
        assert again["amount"] == 7999.0 and again["duration_unit"] == "year" and again["active"] is False
