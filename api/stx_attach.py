"""The STX Index beside every report row.

STX is the platform's own measure, so every report that ranks channels carries it: each row gets the channel's current STX Index (the 7-day score the STX Index screen shows, with its confidence), and each
report gets a headline that names the channel with the highest STX and the average of the channels in it. The score shown is the one the rest of StatAxis shows (pulled toward 50 when data is thin);
a channel with no score has ``stx`` None and is shown as a dash, never as zero.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from api.market_common import rnd
from api.media_intelligence import market_report
from api.ttl_cache import ttl_cache

STX_PERIOD = "7d"
STX_NOTE = "STX Index: StatAxis's own 0-100 score for a channel (audience, momentum, consistency and more), shown as of the report time over the last 7 days; a dash means not enough data."


@ttl_cache(stale=True)
def stx_map(session: Session, *, now: datetime | None = None, period: str = STX_PERIOD) -> dict[int, dict[str, Any]]:
    report = market_report(session, as_of=now, period=period, stream_scope="all", limit=200)
    out: dict[int, dict[str, Any]] = {}
    for row in report["channels"]:
        x = row.get("stx") or {}
        shown = x.get("display_score") if x.get("display_score") is not None else x.get("score")
        if shown is not None:
            out[row["channel_id"]] = {"score": rnd(shown, 1), "confidence": x.get("confidence"), "preliminary": bool(x.get("preliminary"))}
    return out


def attach(rows: list[dict[str, Any]], stx: dict[int, dict[str, Any]]) -> None:
    """Give each row (a dict with channel_id) its STX, or None."""
    for r in rows:
        r["stx"] = stx.get(r["channel_id"])


def headline(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The channel with the highest STX in these rows, the average, and how many rows have a score; None when none has."""
    scored = [r for r in rows if r.get("stx")]
    if not scored:
        return None
    best = max(scored, key=lambda r: r["stx"]["score"])
    return {"leader": best["name"], "leader_score": best["stx"]["score"], "average": rnd(sum(r["stx"]["score"] for r in scored) / len(scored), 1), "scored": len(scored), "of": len(rows), "note": STX_NOTE}
