from api.package_config import list_package_slots, update_package_slot
from collector.storage import create_database
from sqlalchemy.orm import Session


def test_reserved_slots_are_created_and_empty(tmp_path):
    engine = create_database(f"sqlite:///{tmp_path / 'packages.db'}")
    with Session(engine) as session:
        rows = list_package_slots(session)
    assert [row["slot"] for row in rows] == list(range(5, 41))
    assert all(row["name"] is None and row["criteria"] == [] and row["amount"] is None and not row["active"] for row in rows)


def test_package_slot_can_be_configured_without_changing_slot_identity(tmp_path):
    engine = create_database(f"sqlite:///{tmp_path / 'packages.db'}")
    with Session(engine) as session:
        saved = update_package_slot(session, 12, {"name": "Newsroom Pro", "criteria": ["12 channels", "Daily reports"], "amount": "4999.00", "currency": "INR", "active": True})
        assert saved == {"slot": 12, "name": "Newsroom Pro", "criteria": ["12 channels", "Daily reports"], "amount": 4999.0, "currency": "INR", "active": True, "configured": True}
        again = update_package_slot(session, 12, {"amount": None, "active": False})
        assert again["slot"] == 12
        assert again["name"] == "Newsroom Pro"
        assert again["criteria"] == ["12 channels", "Daily reports"]
        assert again["amount"] is None
        assert again["active"] is False
