from api.access import plan_video_access_policy, video_access_policy
from api.plans import SXPlan


def test_free_package_has_no_premium_video_actions() -> None:
    policy = plan_video_access_policy(SXPlan.FREE)
    assert policy.can_evaluate_url is False
    assert policy.can_download_report is False
    assert policy.can_add_video is False
    assert policy.can_remove_video is False


def test_premium_packages_can_evaluate_and_download_but_not_manage_catalogue() -> None:
    for plan in SXPlan:
        if plan is SXPlan.FREE:
            continue
        policy = plan_video_access_policy(plan)
        assert policy.can_evaluate_url is True
        assert policy.can_download_report is True
        assert policy.can_add_video is False
        assert policy.can_remove_video is False


def test_legacy_roles_map_to_final_sx_packages() -> None:
    assert video_access_policy("journalist").can_evaluate_url is True
    assert video_access_policy("data_scientist").can_download_report is True
    assert video_access_policy("corporate").can_evaluate_url is True
    assert video_access_policy("free").can_evaluate_url is False
