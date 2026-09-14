import pytest

from api.access import UserRole, extract_youtube_video_id, require_capability, video_access_policy


def test_admin_can_add_remove_evaluate_and_download() -> None:
    policy = video_access_policy(UserRole.ADMIN)
    assert policy.can_add_video
    assert policy.can_remove_video
    assert policy.can_evaluate_url
    assert policy.can_download_report


@pytest.mark.parametrize(
    "role",
    [UserRole.PAID, UserRole.CORPORATE, UserRole.JOURNALIST, UserRole.DATA_SCIENTIST],
)
def test_premium_roles_can_evaluate_and_download_but_not_manage_catalog(role: UserRole) -> None:
    policy = video_access_policy(role)
    assert not policy.can_add_video
    assert not policy.can_remove_video
    assert policy.can_evaluate_url
    assert policy.can_download_report
    require_capability(policy, "can_evaluate_url")
    require_capability(policy, "can_download_report")
    with pytest.raises(PermissionError):
        require_capability(policy, "can_remove_video")


def test_free_role_requires_premium_for_evaluation_and_download() -> None:
    policy = video_access_policy(UserRole.FREE)
    assert not policy.can_evaluate_url
    assert not policy.can_download_report
    with pytest.raises(PermissionError):
        require_capability(policy, "can_evaluate_url")
    with pytest.raises(PermissionError):
        require_capability(policy, "can_download_report")


def test_extracts_watch_and_short_urls() -> None:
    assert extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_video_id("https://youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    ["", "https://example.com/watch?v=dQw4w9WgXcQ", "javascript:dQw4w9WgXcQ"],
)
def test_rejects_invalid_urls(url: str) -> None:
    with pytest.raises(ValueError):
        extract_youtube_video_id(url)
