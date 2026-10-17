"""The public methodology: what StatAxis measures and how, with a version and a dated changelog. Everything here is read from the same constants the calculations use (weights, thresholds), so the page
cannot drift from the code; the changelog is the one hand-written part, and each entry names what changed.
"""

from __future__ import annotations

from typing import Any

from api.social import METHOD as SOCIAL_METHOD
from collector.classification import LEGACY_SHORT_MAX_SECONDS, SHORT_MAX_SECONDS, SHORTS_EXTENDED_FROM
from metrics.feeds import min_primary_hours
from metrics.stx_index import WEIGHTS

VERSION = "STX v0"
CHANGELOG: list[dict[str, Any]] = [
    {"date": "2026-10-10", "version": "v0", "changes": ["First recording of live audiences and uploads began.", "STX Index v0: seven signals with the weights listed here; a signal with no data is left out and the rest are re-weighted, never counted as zero."]},
    {"date": "2026-10-11", "version": "v0", "changes": ["Primary, Secondary and All feeds defined from YouTube's own start time (a stream live for 30 days or more is the primary feed).", "Shorts are collected but kept out of rankings, STX and analysis."]},
    {"date": "2026-10-12", "version": "v0", "changes": ["The window called Today now starts at midnight Indian time (it started at 00:00 UTC, 5:30 am in India), and is compared with yesterday over the same hours.", "Primary feeds of the tracked channels were added to the measurement; earlier figures understate Primary and All for these channels."]},
    {"date": "2026-10-13", "version": "v0", "changes": ["Market-wide STX is worked out from up to 250 evenly spread readings per channel plus every reading of the last twenty minutes, instead of every reading (the totals shown are still exact). The weights and formulas did not change.", "Hours watched, audience spikes with the stream behind them, audience movement, daily and weekly notes, prime-time forecasts with a published track record, alerts and a data-completeness figure were added."]},
    {"date": "2026-10-16", "version": "v0", "changes": ["Facebook, Instagram and X were added beside YouTube: followers, growth, reactions to posts (likes, comments, shares, and views where the platform gives them), engagement rate and the best posts. The figures come only from each platform's official API or from sheets supplied by a channel or entered by StatAxis, and every figure shows when it was read. The STX Index and the IFX Score are unchanged and still use YouTube data only."]},
    {"date": "2026-10-17", "version": "v0", "changes": ["The tracked channels are treated as the final list. Their new live streams are now looked for about every 30 minutes (before: only in the full pass, about every 107 minutes, so the average new stream was found 49 minutes late) and each is tracked as a secondary stream from the moment it is found. The Primary stream of a channel is still its long-running main stream."]},
]
SIGNALS = [
    ("audience", "Change in concurrent viewers against the previous window: 50 + percent change, limited to 0-100."),
    ("growth", "Change in views against the previous window: 50 + percent change, limited to 0-100."),
    ("momentum", "Viewers gained or lost per minute at the latest interval: 50 + (change per minute / 2), limited to 0-100."),
    ("acceleration", "How that rate itself changed at the latest interval: 50 + change per minute squared, limited to 0-100."),
    ("consistency", "Share of the recent intervals whose view growth pointed the same way as the latest one."),
    ("competitive_position", "100 divided by the channel's rank among the channels compared."),
    ("anomaly_event", "50 + 10 x the robust z-score (median and median absolute deviation) of the latest view count against its own history."),
]


def methodology() -> dict[str, Any]:
    return {
        "version": VERSION,
        "stx": {"formula": "STX = sum(signal x weight) / sum(weights of the signals that exist). Confidence = sum(weights of the signals that exist) / 1.00 x 100. The shown score is 50 + (STX - 50) x confidence / 100; below 50% confidence a score is marked preliminary.",
                "weights": WEIGHTS, "signals": [{"name": n, "definition": d} for n, d in SIGNALS], "scale": "Every signal runs 0-100; 50 is neutral."},
        "collection": {"source": "YouTube Data API v3 only (no scraping).", "live_reading": "Each live stream is read about every 75 seconds; the interval is set by the YouTube quota and is shown on the status page.",
                       "uploads": "Each channel's newest uploads and its channel statistics are read in a pass about every 107 minutes. New live streams of the tracked channels are looked for about every 30 minutes in between, and each is tracked as a secondary stream from the moment it is found."},
        "feeds": {"primary": f"Among a channel's concurrent live streams, the one live the longest, and for at least {min_primary_hours() / 24:g} days, by YouTube's own start time.", "secondary": "Every other live stream of the channel.",
                  "all": "Primary plus secondary. With no stream live that long, all viewers count as secondary, so All is never understated."},
        "shorts": f"A video of {SHORT_MAX_SECONDS} seconds or less ({LEGACY_SHORT_MAX_SECONDS} seconds or less if uploaded before {SHORTS_EXTENDED_FROM:%d %B %Y}) is a Short. Shorts are collected and can be viewed, but are not counted in rankings, STX or analysis.",
        "measures": [
            {"name": "Average concurrent viewers", "definition": "On a one-minute grid, the sum of the latest reading of each live stream of the channel (a reading counts for up to 180 seconds), averaged over the minutes the channel was live. Nothing is interpolated."},
            {"name": "Peak concurrent viewers", "definition": "The highest one-minute total."},
            {"name": "Hours watched (live)", "definition": "The sum over the grid of the minute's concurrent viewers x one minute, in hours: viewer-hours of live viewing observed."},
            {"name": "Views gained", "definition": "For each video: its last reading in the window minus its first (never below zero); a channel's figure adds its videos."},
            {"name": "Share", "definition": "A channel's figure divided by the total of its market (group and language)."},
        ],
        "windows": "All times are Indian time. Last hour, 3 hours and 6 hours end now; Today runs from midnight; prime time is the hourly slots 17:00-23:00. Each window is compared with the one of equal length before it.",
        "forecasts": "Expected prime-time audience = median of the same slot over up to 7 earlier days, written down at 06:00 IST and scored afterwards; a hit is within 20%. The track record is shown on the Forecasts screen.",
        "social": {"source": "Facebook, Instagram and X figures come only from each platform's official API, with the access the platform grants StatAxis, or from sheets that a channel supplies or StatAxis staff enter. Nothing is scraped. Each figure carries the time it was read.",
                   "method": SOCIAL_METHOD, "limits": ["The STX Index and the IFX Score use YouTube data only; the social figures are shown beside them, not inside them.", "Reach and impressions are not public on any of the three platforms, so the engagement rate says how many people reacted, not how many saw a post.", "Instagram can be read only for business and creator accounts; Facebook posts of a page need the platform's public-content permission; X is read only as far as the access StatAxis has bought."]},
        "limits": ["Figures are measured on YouTube, not on television, and are not TV ratings.", "A flag in the authenticity radar is an unusual pattern in public numbers, not proof of anything."],
        "changelog": CHANGELOG,
    }
