"""YouTube data client used by the StatAxis collector."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Self

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
