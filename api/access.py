"""Authorization and validation rules for dashboard video workflows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qs, urlparse


class UserRole(StrEnum):
    """Dashboard roles relevant to video management and evaluation."""

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
    reason: str


def video_access_policy(role: UserRole | str) -> VideoAccessPolicy:
    """Return the least-privilege video capabilities for a dashboard role."""
    try:
        resolved = UserRole(role)
    except ValueError as exc:
        raise ValueError(f"unknown user role: {role}") from exc

    if resolved is UserRole.ADMIN:
        return VideoAccessPolicy(True, True, True, "admin access")

    if resolved in {
        UserRole.PAID,
        UserRole.CORPORATE,
        UserRole.JOURNALIST,
        UserRole.DATA_SCIENTIST,
    }:
        return VideoAccessPolicy(False, False, True, "evaluation access")

    return VideoAccessPolicy(False, False, False, "premium evaluation access required")


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
        elif parsed.path.startswith("/shorts/"):
            video_id = parsed.path.split("/", 2)[2]
        elif parsed.path.startswith("/live/"):
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
    if capability not in {"can_add_video", "can_remove_video", "can_evaluate_url"}:
        raise ValueError(f"unknown capability: {capability}")
    if not getattr(policy, capability):
        raise PermissionError(policy.reason)
