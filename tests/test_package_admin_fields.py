from api.package_config import update_package_slot
from collector.storage import create_database
from sqlalchemy.orm import Session


def test_package_admin_fields_can_change_duration_and_privileges(tmp_path):
    engine = create_database(f"sqlite:///{tmp_path / 'packages.db'}")
    with Session(engine) as session:
        first = update_package_slot(session, 40, {"name":"Custom", "criteria":["A"], "privileges":["B"], "amount":100, "duration_value":1, "duration_unit":"month", "active":True})
        second = update_package_slot(session, 40, {"name":"Custom 2", "privileges":["C"], "amount":200, "duration_value":1, "duration_unit":"year"})
        assert first["slot"] == second["slot"] == 40
        assert second["name"] == "Custom 2" and second["privileges"] == ["C"]
        assert second["amount"] == 200.0 and second["duration_unit"] == "year"
