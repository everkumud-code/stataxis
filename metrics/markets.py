"""Channel categories and languages, and the market labels built from them, e.g. "Hindi News", "Hindi Business News", "Tamil News".

A channel has a *segment* (its category: what kind of publisher it is) and a *language*. The owner's classification:

  categories   news = Main stream, business = Business news, entertainment = Entertainment, commentator = Political commentary, journalist = Individual journalist
               (and print, party, leader, creator, brand for the other kinds of channel)
  languages    Hindi, English, Bangla, Tamil, Telugu, Kannada, Bhojpuri, Hindi (Regional), French, US English, UK English, Arabic, and Other (everything else)

The two are never mixed: a business news channel is never in "Hindi News", it is in "Hindi Business News". The market label of a report is the language and the category together.
"""

from __future__ import annotations

DEFAULT_SEGMENT = "news"

SEGMENTS: dict[str, str] = {
    "news": "Main stream",
    "business": "Business news",
    "entertainment": "Entertainment",
    "commentator": "Political commentary",
    "journalist": "Individual journalist",
    "print": "Print media",
    "party": "Political parties",
    "leader": "Political leaders",
    "creator": "Creators & influencers",
    "brand": "Brands & entertainment",
}

KNOWN_LANGUAGES = ["Hindi", "English", "Bangla", "Tamil", "Telugu", "Kannada", "Bhojpuri", "Hindi (Regional)", "French", "US English", "UK English", "Arabic"]
_ALIASES = {"arabi": "arabic", "bengali": "bangla", "hin": "hindi", "eng": "english"}

# categories whose market is named with the language ("Hindi Business News"), with the words that follow the language
_LANGUAGE_MARKETS = {"news": "News", "business": "Business News", "entertainment": "Entertainment", "commentator": "Political Commentary", "journalist": "Individual Journalists"}
_FIXED_MARKETS = {
    "print": "Print Media",
    "party": "Political Parties & Leaders",
    "leader": "Political Parties & Leaders",
    "creator": "Creators & Influencers",
    "brand": "Brands & Entertainment",
}


def language_group(language: str | None) -> str:
    """The group a language belongs to: Hindi, English (US and UK English too), Hindi (Regional) on its own, Unknown, or Regional (every other language)."""
    value = (language or "").strip().lower()
    if not value or value == "unknown":
        return "Unknown"
    if value == "hindi (regional)":
        return "Hindi (Regional)"
    if value.startswith("hi") or value in {"hindi", "hin"}:
        return "Hindi"
    if value.startswith("en") or "english" in value or value == "eng":
        return "English"
    return "Regional"


def language_matches(language: str | None, target: str | None) -> bool:
    """Whether a channel's language is the one asked for: an exact language (Tamil, US English ...), a group (Hindi, English, Regional) or 'Other' (a language that is not in the list)."""
    want = _ALIASES.get((target or "").strip().lower(), (target or "").strip().lower())
    if not want:
        return True
    value = _ALIASES.get((language or "").strip().lower(), (language or "").strip().lower())
    if want == "other":
        return value not in {k.lower() for k in KNOWN_LANGUAGES} and language_group(language) not in {"Hindi", "English"}
    return language_group(language).lower() == want or value == want


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
    lang = (language or "").strip()
    if key in _FIXED_MARKETS:
        return _FIXED_MARKETS[key]
    words = _LANGUAGE_MARKETS.get(key, "News")
    return words if not lang or lang.lower() == "unknown" else f"{lang} {words}"
