"""Small, quota-aware client for the public YouTube Data API v3."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Self

import httpx
from dotenv import load_dotenv


BASE_URL = "https://www.googleapis.com/youtube/v3"

# Load the project's local .env without requiring the user to configure
# Windows environment variables. The .env file is ignored by Git.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


class YouTubeAPIError(RuntimeError):
    """Raised when YouTube returns an unsuccessful API response."""


class YouTubeClient:
    """Minimal client using an API key and explicit API methods.

    The client deliberately does not expose generic search functionality.
    STAXIS should prefer registered channel IDs and their uploads playlists
    to keep collection deterministic and quota-efficient.
    """

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
        response = self.client.get(
            f"{BASE_URL}/{resource}",
            params={**params, "key": self.api_key},
        )
        if response.is_error:
            detail = response.text[:1000]
            raise YouTubeAPIError(
                f"YouTube API {response.status_code} for {resource}: {detail}"
            )
        return response.json()

    def get_channel(self, channel_id: str) -> dict[str, Any]:
        """Return channel metadata including the uploads playlist ID."""
        data = self._get(
            "channels",
            {"part": "snippet,contentDetails,statistics", "id": channel_id},
        )
        items = data.get("items", [])
        if not items:
            raise YouTubeAPIError(f"Channel not found: {channel_id}")
        return items[0]

    def list_uploads(
        self, uploads_playlist_id: str, max_results: int = 25
    ) -> dict[str, Any]:
        """List recent videos from a channel's system uploads playlist."""
        return self._get(
            "playlistItems",
            {
                "part": "snippet,contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": min(max_results, 50),
            },
        )

    def get_videos(self, video_ids: list[str]) -> list[dict[str, Any]]:
        """Fetch metadata/statistics for up to 50 video IDs in one request."""
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
