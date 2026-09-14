from api.plans import SXPlan, all_plans, get_plan


def test_sx_plan_catalog_has_final_public_names() -> None:
    plans = all_plans()
    assert [plan.name for plan in plans] == [
        "SX Free",
        "SX Idea",
        "SX Intelligence",
        "SX Analyst",
        "SX Pro",
        "SX Corporate",
        "SX Enterprise",
    ]
    assert [plan.promise for plan in plans] == [
        "Explore the Data",
        "Discover the Signal",
        "Understand the Signal",
        "Analyse the Signal",
        "Act on the Signal",
        "Team Intelligence",
        "Institutional Intelligence",
    ]


def test_corporate_has_five_seats_and_enterprise_is_uncapped() -> None:
    assert get_plan(SXPlan.CORPORATE).max_seats == 5
    assert get_plan(SXPlan.ENTERPRISE).max_seats is None


def test_unknown_plan_is_rejected() -> None:
    try:
        get_plan("sx_unknown")
    except ValueError as exc:
        assert "unknown SX plan" in str(exc)
    else:
        raise AssertionError("unknown package should fail")
