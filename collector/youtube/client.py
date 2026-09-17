"""YouTube data client used by the StatAxis collector."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Self
from urllib.parse import unquote, urlparse

import httpx
from dotenv import load_dotenv

from collector.youtube.quota import DEFAULT_BUDGET, QuotaGuardError

BASE_URL = "https://www.googleapis.com/youtube/v3"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


class YouTubeAPIError(RuntimeError):
    """Raised when YouTube returns an unsuccessful API response."""


class YouTubeClient:
    """HTTP client with bounded request rate and request budget."""

    def __init__(self, api_key: str | None = None, timeout: float = 20.0) -> None:
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        if not self.api_key:
            raise ValueError("YOUTUBE_API_KEY is not configured")
        self.client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _get(self, resource: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            DEFAULT_BUDGET.acquire()
        except QuotaGuardError:
            raise
        response = self.client.get(
            f"{BASE_URL}/{resource}",
            params={**params, "key": self.api_key},
        )
        if response.status_code == 429:
            raise YouTubeAPIError("YouTube request temporarily rate limited")
        if response.is_error:
            detail = response.text[:1000]
            raise YouTubeAPIError(f"YouTube API {response.status_code} for {resource}: {detail}")
        return response.json()

    def get_channel(self, channel_id: str) -> dict[str, Any]:
        data = self._get(
            "channels",
            {"part": "snippet,contentDetails,statistics", "id": channel_id},
        )
        items = data.get("items", [])
        if not items:
            raise YouTubeAPIError(f"Channel not found: {channel_id}")
        return items[0]

    def resolve_channel_url(self, url: str) -> dict[str, Any]:
        """Resolve a public channel URL to YouTube channel metadata."""
        candidate = url.strip()
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("YouTube channel URL must use http or https")
        host = parsed.netloc.lower().split(":", 1)[0]
        if host not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            raise ValueError("URL must be a YouTube channel URL")
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if not parts:
            raise ValueError("YouTube channel URL is required")
        if parts[0] == "channel" and len(parts) >= 2:
            return self.get_channel(parts[1])
        if parts[0].startswith("@"):
            handle = parts[0][1:]
            if not handle:
                raise ValueError("invalid YouTube channel handle")
            data = self._get("channels", {"part": "snippet,contentDetails,statistics", "forHandle": handle})
            items = data.get("items", [])
            if not items:
                raise YouTubeAPIError(f"Channel not found for handle: @{handle}")
            return items[0]
        if parts[0] in {"c", "user"} and len(parts) >= 2:
            handle = parts[1]
            data = self._get("search", {"part": "snippet", "q": handle, "type": "channel", "maxResults": 5})
            items = data.get("items", [])
            if not items:
                raise YouTubeAPIError(f"Channel not found: {handle}")
            channel_id = str(items[0].get("snippet", {}).get("channelId") or items[0].get("id", {}).get("channelId") or "")
            if not channel_id:
                raise YouTubeAPIError(f"Channel ID not found: {handle}")
            return self.get_channel(channel_id)
        raise ValueError("Use a YouTube /channel/ID or /@handle URL")

    def list_uploads(self, uploads_playlist_id: str, max_results: int = 25) -> dict[str, Any]:
        return self._get(
            "playlistItems",
            {
                "part": "snippet,contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": min(max_results, 50),
            },
        )

    def get_videos(self, video_ids: list[str]) -> list[dict[str, Any]]:
        if not video_ids:
            return []
        if len(video_ids) > 50:
            raise ValueError("get_videos accepts at most 50 video IDs")
        data = self._get(
            "videos",
            {
                "part": "snippet,contentDetails,statistics,liveStreamingDetails",
                "id": ",".join(video_ids),
            },
        )
        return data.get("items", [])
