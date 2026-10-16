"""What every platform connector hands back, the errors it can raise, and the one HTTP call all of them use."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

PLATFORM_LABEL = {"facebook": "Facebook", "instagram": "Instagram", "x": "X"}
TEXT_KEPT = 280   # only the start of a post's text is kept, enough to see what the post was about


class SocialError(Exception):
    """A platform refused, could not be reached, or cannot give this account's figures. ``code`` says which; the message is safe to show (it never holds a key)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class AccountSnapshot:
    followers: int | None = None
    following: int | None = None
    posts_total: int | None = None
    display_name: str | None = None
    external_id: str | None = None
    url: str | None = None


@dataclass
class PostSnapshot:
    post_id: str
    posted_at: datetime | None = None
    text: str | None = None
    permalink: str | None = None
    media_type: str | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    views: int | None = None


@dataclass
class Fetched:
    account: AccountSnapshot
    posts: list[PostSnapshot] = field(default_factory=list)


Opener = Callable[[urllib.request.Request, float], Any]


def _default_open(req: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(req, timeout=timeout)   # noqa: S310 - fixed https addresses of the platforms


def http_json(url: str, *, headers: dict[str, str] | None = None, timeout: float = 25.0, opener: Opener | None = None) -> dict[str, Any]:
    """GET a JSON document. A refusal comes back as a SocialError with a code (auth, rate_limited, not_found, error); the access key in the address is never put in a message."""
    req = urllib.request.Request(url, headers={"User-Agent": "StatAxis/1.0", "Accept": "application/json", **(headers or {})})
    try:
        with (opener or _default_open)(req, timeout) as res:
            return json.loads(res.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body: dict[str, Any] = {}
        try:
            body = json.loads(exc.read().decode("utf-8") or "{}")
        except (ValueError, OSError):
            pass
        raise _error_from(exc.code, body) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SocialError("error", "the platform could not be reached") from exc
    except ValueError as exc:
        raise SocialError("error", "the platform answered with something that is not JSON") from exc


def _error_from(status: int, body: dict[str, Any]) -> SocialError:
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    message = str(err.get("message") or body.get("detail") or body.get("title") or "")[:200]
    code = err.get("code")
    if status == 429 or code in (4, 17, 32, 613) or "rate limit" in message.lower():
        return SocialError("rate_limited", "the platform's rate limit was reached; it will be tried again later")
    if status in (401,) or code in (190, 102) or "access token" in message.lower():
        return SocialError("auth", "the platform refused the access key (wrong, expired or without the needed permission)")
    if status == 403 or code in (10, 200, 299):
        return SocialError("unsupported", "the platform does not allow this key to read this account (a missing permission or an account type that is not public)" + (f": {message}" if message else ""))
    if status == 404 or code in (803, 100, 110) or "does not exist" in message.lower():
        return SocialError("not_found", "the platform does not know this account (check the handle)")
    return SocialError("error", f"the platform answered {status}" + (f": {message}" if message else ""))


def to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        n = int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def parse_time(value: Any) -> datetime | None:
    """A platform's timestamp ("2026-10-12T09:30:00+0000", "...Z", or a plain date) as an aware UTC time."""
    if not value:
        return None
    text = str(value).strip()
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)    # +0000 -> +00:00
    text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def clip(text: Any) -> str | None:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value[:TEXT_KEPT] or None


def clean_handle(raw: str, platform: str) -> str:
    """The handle without @, address or trailing slash: ``https://x.com/stataxis/`` and ``@stataxis`` both become ``stataxis``."""
    value = (raw or "").strip()
    value = re.sub(r"^https?://(www\.|m\.|mobile\.)?", "", value, flags=re.I)
    value = re.sub(r"^(facebook\.com|fb\.com|instagram\.com|x\.com|twitter\.com)/", "", value, flags=re.I)
    value = value.split("?")[0].split("#")[0].strip("/")
    if platform == "facebook" and value.lower().startswith("pages/"):
        value = value.split("/")[-1]
    value = value.split("/")[0].lstrip("@")
    return value[:255]


def valid_handle(handle: str, platform: str) -> bool:
    if platform == "x":
        return bool(re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle))
    if platform == "instagram":
        return bool(re.fullmatch(r"[A-Za-z0-9._]{1,30}", handle))
    return bool(re.fullmatch(r"[A-Za-z0-9.\-_]{1,100}", handle))


def quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")
