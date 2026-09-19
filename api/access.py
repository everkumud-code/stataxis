"""Authorization and validation rules for dashboard video workflows."""

from __future__ import annotations

from api.errors import AuthorizationError

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qs, urlparse

from api.plans import SXPlan, get_plan


class UserRole(StrEnum):
    """Legacy dashboard roles retained for compatibility with existing API clients."""

    ADMIN = "admin"
    FREE = "free"
    PAID = "paid"
    CORPORATE = "corporate"
    JOURNALIST = "journalist"
    DATA_SCIENTIST = "data_scientist"


@dataclass(frozen=True)
class VideoAccessPolicy:
    """Explicit capabilities used by dashboard/API authorization."""

    can_add_video: bool
    can_remove_video: bool
    can_evaluate_url: bool
    can_download_report: bool
    reason: str


def _premium_policy(reason: str) -> VideoAccessPolicy:
    return VideoAccessPolicy(False, False, True, True, reason)


def plan_video_access_policy(plan: SXPlan | str) -> VideoAccessPolicy:
    """Return video capabilities for a customer-facing SX package."""
    definition = get_plan(plan)
    if definition.code is SXPlan.FREE:
        return VideoAccessPolicy(False, False, False, False, "premium access required")
    return _premium_policy(f"{definition.name} access")


def video_access_policy(role: UserRole | str) -> VideoAccessPolicy:
    """Return least-privilege capabilities for a legacy dashboard role.

    The customer-facing authorization model is package-based; this role adapter
    remains for older callers until account/subscription records are migrated.
    """
    try:
        resolved = UserRole(role)
    except ValueError as exc:
        raise ValueError(f"unknown user role: {role}") from exc

    if resolved is UserRole.ADMIN:
        return VideoAccessPolicy(True, True, True, True, "admin access")

    role_to_plan = {
        UserRole.FREE: SXPlan.FREE,
        UserRole.PAID: SXPlan.PRO,
        UserRole.CORPORATE: SXPlan.CORPORATE,
        UserRole.JOURNALIST: SXPlan.IDEA,
        UserRole.DATA_SCIENTIST: SXPlan.ANALYST,
    }
    return plan_video_access_policy(role_to_plan[resolved])


def extract_youtube_video_id(url: str) -> str:
    """Validate a public YouTube URL and return its video ID."""
    candidate = url.strip()
    if not candidate:
        raise ValueError("YouTube URL is required")

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("YouTube URL must use http or https")

    host = parsed.netloc.lower().split(":", 1)[0]
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith("/shorts/") or parsed.path.startswith("/live/"):
            video_id = parsed.path.split("/", 2)[2]
        else:
            video_id = ""
    elif host == "youtu.be":
        video_id = parsed.path.lstrip("/").split("/", 1)[0]
    else:
        video_id = ""

    if not video_id or len(video_id) != 11 or not video_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("invalid YouTube video URL")

    return video_id


def require_capability(policy: VideoAccessPolicy, capability: str) -> None:
    """Raise PermissionError unless a policy explicitly grants a capability."""
    if capability not in {
        "can_add_video",
        "can_remove_video",
        "can_evaluate_url",
        "can_download_report",
    }:
        raise ValueError(f"unknown capability: {capability}")
    if not getattr(policy, capability):
        raise AuthorizationError(policy.reason)
