"""Market segments and labels, e.g. "Hindi News", "Business News", "Print Media".

A channel has a *segment* (what kind of publisher it is) and a *language*. The segment
decides how channels are grouped into markets for reports:

  news         -> "<Language> News"        (Hindi News, English News, Tamil News ...)
  business     -> "Business News"          (all languages together)
  print        -> "Print Media"            (newspaper / magazine YouTube channels)
  party        -> "Political Parties & Leaders"
  leader       -> "Political Parties & Leaders"
  commentator  -> "Political Commentators"
"""

from __future__ import annotations

DEFAULT_SEGMENT = "news"

SEGMENTS: dict[str, str] = {
    "news": "News",
    "business": "Business News",
    "print": "Print Media",
    "party": "Political Parties",
    "leader": "Political Leaders",
    "commentator": "Political Commentators",
}

_FIXED_MARKETS = {
    "business": "Business News",
    "print": "Print Media",
    "party": "Political Parties & Leaders",
    "leader": "Political Parties & Leaders",
    "commentator": "Political Commentators",
}


def normalize_segment(value: str | None) -> str:
    """Return a known segment key; blank means the default (news). Unknown values raise."""
    key = (value or "").strip().lower()
    if not key:
        return DEFAULT_SEGMENT
    if key not in SEGMENTS:
        raise ValueError(f"segment must be one of: {', '.join(SEGMENTS)}")
    return key


def market_label(segment: str | None, language: str | None) -> str:
    """Market a channel belongs to for reporting."""
    key = (segment or "").strip().lower() or DEFAULT_SEGMENT
    if key in _FIXED_MARKETS:
        return _FIXED_MARKETS[key]
    lang = (language or "").strip()
    if not lang or lang.lower() == "unknown":
        return "News"
    return f"{lang} News"
