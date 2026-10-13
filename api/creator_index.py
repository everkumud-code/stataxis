"""The IFX Score: Impact, Followership, eXposure. A score for people who publish videos and Shorts instead of going live (influencers, independent journalists, commentators).

The STX Index for channels leans on live audiences. A creator has none, so the IFX Score is built from what a creator does have in public, under three pillars:

  Impact        how strongly the content lands: depth of reaction (likes and comments per view), conversation (comments per 1,000 views), staying power (old videos still earning) and the best upload against the size of the audience
  Followership  the audience behind the creator: its size, its loyalty (views per subscriber), its growth, reaching beyond the creator's own subscribers and, for those who go live, the turnout at a live stream
  eXposure      how far and how often the creator is seen: reach per upload, regular publishing, steady results, hit rate (how often an upload beats the typical peer upload), fresh uploads, momentum (are newer uploads doing better
                than older ones) and the early pull of new uploads

Four of the sixteen parts (best upload against audience size, reaching beyond subscribers, momentum, early pull of new uploads) do not depend on how big the creator already is, so a small creator who makes things people
want can score well on them; the pillars keep their 35 / 35 / 30 weights.

Each part is ranked against the other creators in the same comparison (not against a fixed scale), the parts are combined, and the result is pulled toward 50 when STAXIS has little data,
exactly as the channel index does. Saves, shares and conversions are not public on YouTube, so they are not used, and exposure on other platforms is not seen: this score is YouTube only
and says so. It is never shown as more certain than the data allows: every row carries a confidence, a plain-words profile and the reason behind a high or low score.
"""

from __future__ import annotations

from api.ttl_cache import ttl_cache

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from api import authenticity
from api.market_common import channel_videos, latest_observations, mean, now_utc, parse_published, percentile_rank, pick_channels, rnd, stdev, utc
from api.market_tools import _subscribers
from collector.storage import Observation, Video

INDEX_NAME = "IFX Score"  # the one place the name is set
TAGLINE = "Impact · Followership · eXposure"
PARTS = {  # part: (pillar, weight)
    "engagement": ("impact", 0.09), "conversation": ("impact", 0.06), "staying": ("impact", 0.12), "bestshot": ("impact", 0.08),
    "size": ("followership", 0.04), "loyalty": ("followership", 0.10), "growth": ("followership", 0.08), "live": ("followership", 0.06), "beyond": ("followership", 0.07),
    "reach": ("exposure", 0.06), "cadence": ("exposure", 0.07), "steadiness": ("exposure", 0.04), "hitrate": ("exposure", 0.05), "freshness": ("exposure", 0.03), "momentum": ("exposure", 0.03), "earlypull": ("exposure", 0.02),
}
WEIGHTS = {k: w for k, (_p, w) in PARTS.items()}
PILLARS = {"impact": "Impact", "followership": "Followership", "exposure": "eXposure"}
PILLAR_WEIGHTS = {p: round(sum(w for _k, (pp, w) in PARTS.items() if pp == p), 2) for p in PILLARS}
LABELS = {"engagement": "Depth of reaction", "conversation": "Conversation in the comments", "staying": "Old videos still earn", "size": "Audience size", "loyalty": "Views per subscriber",
          "growth": "Audience growth", "live": "Live turnout", "reach": "Reach per upload", "cadence": "Regular publishing", "steadiness": "Steady results", "hitrate": "Hit rate", "freshness": "Fresh uploads",
          "bestshot": "Best upload against audience size", "beyond": "Reaching beyond own subscribers", "momentum": "Momentum (newer uploads against older)", "earlypull": "Early pull of new uploads"}
NOT_MEASURED = ["Saves, shares and conversions (YouTube does not publish them for other people's videos)", "Exposure on other platforms (this score is YouTube only)"]
METHOD = (
    f"The {INDEX_NAME} ({TAGLINE}) ranks each creator against the others in the comparison on sixteen measured parts under three pillars. "
    "Impact: depth of reaction ((likes + 5 x comments) / views), conversation (comments per 1,000 views) and staying power (how fast videos older than 10 days keep gaining views) and best upload against audience size (the most-viewed upload / subscribers). "
    "Followership: audience size (subscribers), loyalty (median views of a mature upload / subscribers), growth (subscriber change, needs 3+ days of history) live turnout (median peak viewers of the creator's own live streams / subscribers; only for creators who went live) and reaching beyond subscribers (the share of mature uploads watched more times than the creator has subscribers). "
    "eXposure: reach per upload (median views), regular publishing (uploads per week and how even the gaps are), steady results (how little views vary from upload to upload), hit rate (the share of mature uploads that reach at least the typical peer upload) fresh uploads (how recently the creator last published), momentum (median views of the newest third of mature uploads / the oldest third; needs 6+ uploads) and early pull (median views of uploads 2 to 10 days old / subscribers). "
    "Four of these parts (best upload, beyond subscribers, momentum, early pull) do not depend on how big the creator already is, so small creators are judged on what their content does, not on how many people follow. "
    "A part STAXIS cannot measure is left out and the others are re-weighted. Live streams are excluded. "
    "The shown score is pulled toward 50 by (1 - confidence), so thin data cannot give a confident-looking score. A creator with open high-risk unusual-viewership flags loses 10 points; "
    "one whose flag an admin confirmed is not scored. Not measured: saves, shares and conversions, and exposure on other platforms."
)
LIVE_CLASSES = {"LIVE", "UPCOMING", "COMPLETED_LIVE", "REPLAY"}


def _first_last(session: Session, video_ids: list[int], since: datetime) -> dict[int, tuple[Observation, Observation]]:
    out: dict[int, tuple[Observation, Observation]] = {}
    for i in range(0, len(video_ids), 400):
        chunk = video_ids[i:i + 400]
        span = select(Observation.video_id, func.min(Observation.observed_at).label("lo"), func.max(Observation.observed_at).label("hi")).where(
            Observation.video_id.in_(chunk), Observation.observed_at >= since, Observation.view_count.is_not(None)).group_by(Observation.video_id).subquery()
        first = {o.video_id: o for o in session.execute(select(Observation).join(span, and_(Observation.video_id == span.c.video_id, Observation.observed_at == span.c.lo))).scalars()}
        last = {o.video_id: o for o in session.execute(select(Observation).join(span, and_(Observation.video_id == span.c.video_id, Observation.observed_at == span.c.hi))).scalars()}
        for vid, f in first.items():
            if vid in last:
                out[vid] = (f, last[vid])
    return out


@ttl_cache(stale=True)
def creator_index(session: Session, *, segment: str | None = None, language: str | None = None, days: int = 30, channel_ids: list[int] | None = None, now: datetime | None = None, with_authenticity: bool = True) -> dict[str, Any]:
    if not 14 <= int(days) <= 90:
        raise ValueError("days must be between 14 and 90")
    days = int(days)
    now = utc(now) if now else now_utc()
    since = now - timedelta(days=days)
    channels, languages = pick_channels(session, segment=segment, language=language, channel_ids=channel_ids)
    ids = [c.id for c in channels]
    videos = channel_videos(session, ids) if ids else []
    mine = [v for v in videos if (m := parse_published(v.published_at)) and since <= m <= now]
    latest = latest_observations(session, [v.id for v in mine])
    mine = [v for v in mine if latest.get(v.id) and latest[v.id].classification not in LIVE_CLASSES and latest[v.id].view_count is not None]
    older = [v for v in mine if (parse_published(v.published_at) or now) <= now - timedelta(days=10)]
    spans = _first_last(session, [v.id for v in older], now - timedelta(days=14))
    subs = _subscribers(session, ids, since - timedelta(days=60))
    live_peaks: dict[int, int] = {}  # a creator's own live streams in the window: the highest viewer count seen at once
    live_vids = [v for v in videos if v.live_started_at and utc(v.live_started_at) >= since]
    for i in range(0, len(live_vids), 400):
        chunk = [v.id for v in live_vids[i:i + 400]]
        for vid, top in session.execute(select(Observation.video_id, func.max(Observation.concurrent_viewers)).where(Observation.video_id.in_(chunk), Observation.concurrent_viewers.is_not(None)).group_by(Observation.video_id)):
            if top and top > 0:
                live_peaks[vid] = int(top)
    by_channel: dict[int, list[Video]] = defaultdict(list)
    for v in mine:
        by_channel[v.channel_id].append(v)

    raw: dict[int, dict[str, Any]] = {}
    for c in channels:
        vs = sorted(by_channel.get(c.id, []), key=lambda v: parse_published(v.published_at))
        s = subs.get(c.id) or {}
        subs_now = s["last"][1] if s.get("last") else None
        history = (s["last"][0] - s["first"][0]).total_seconds() / 86400 if s.get("first") and s.get("last") else 0.0
        mature = [v for v in vs if (parse_published(v.published_at) or now) <= now - timedelta(days=2)] or vs
        mviews = [int(latest[v.id].view_count) for v in mature]
        shorts = [int(latest[v.id].view_count) for v in mature if latest[v.id].classification == "SHORT"]
        longs = [int(latest[v.id].view_count) for v in mature if latest[v.id].classification != "SHORT"]
        react_views = sum(int(latest[v.id].view_count) for v in vs if int(latest[v.id].view_count) >= 1000)
        react = sum(int(latest[v.id].like_count or 0) + 5 * int(latest[v.id].comment_count or 0) for v in vs if int(latest[v.id].view_count) >= 1000)
        gaps = [(parse_published(b.published_at) - parse_published(a.published_at)).total_seconds() / 86400 for a, b in zip(vs, vs[1:])]
        regular = 1 / (1 + (stdev(gaps) / mean(gaps))) if len(gaps) >= 3 and mean(gaps) and stdev(gaps) is not None else None
        per_week = len(vs) / (days / 7)
        rates = []
        for v in older:
            if v.channel_id != c.id or v.id not in spans:
                continue
            f, l = spans[v.id]
            gap_days = (utc(l.observed_at) - utc(f.observed_at)).total_seconds() / 86400
            if gap_days >= 3 and f.view_count:
                rates.append((l.view_count - f.view_count) / f.view_count / gap_days)
        cv = (stdev(mviews) / mean(mviews)) if len(mviews) >= 5 and mean(mviews) else None
        comments = sum(int(latest[v.id].comment_count or 0) for v in vs if int(latest[v.id].view_count) >= 1000)
        own_peaks = [live_peaks[v.id] for v in live_vids if v.channel_id == c.id and v.id in live_peaks]
        last_up = parse_published(vs[-1].published_at) if vs else None
        days_since = max(0.0, (now - last_up).total_seconds() / 86400) if last_up else None
        recent = [int(latest[v.id].view_count) for v in vs if now - timedelta(days=10) <= (parse_published(v.published_at) or now) <= now - timedelta(days=2)]
        third = len(mviews) // 3
        momentum = (median(mviews[-third:]) / median(mviews[:third])) if len(mviews) >= 6 and third >= 2 and median(mviews[:third]) else None   # newest third against oldest third; newer uploads have had less time, so a ratio of 1 or more is convincing
        raw[c.id] = {
            "bestshot": (max(mviews) / subs_now) if len(mviews) >= 3 and subs_now else None,
            "beyond": (sum(1 for x in mviews if x >= subs_now) / len(mviews)) if len(mviews) >= 5 and subs_now else None,
            "momentum": momentum,
            "earlypull": (median(recent) / subs_now) if len(recent) >= 2 and subs_now else None,
            "conversation": (comments / react_views) if react_views else None,
            "live": (median(own_peaks) / subs_now) if own_peaks and subs_now else None, "live_streams": len(own_peaks), "live_peak_median": median(own_peaks) if own_peaks else None,
            "freshness": (1 / (1 + days_since / 7)) if days_since is not None else None, "days_since_last_upload": days_since, "_mviews": mviews,
            "hitrate": None,
            "videos": len(vs), "uploads_video": len([v for v in vs if latest[v.id].classification != "SHORT"]), "uploads_shorts": len([v for v in vs if latest[v.id].classification == "SHORT"]),
            "subscribers": subs_now, "median_views": median(mviews) if mviews else None,
            "loyalty": (median(mviews) / subs_now) if mviews and subs_now else None, "pull": (median(mviews) / subs_now) if mviews and subs_now else None,
            "size": subs_now, "reach": median(mviews) if mviews else None,
            "pull_video": (median(longs) / subs_now) if longs and subs_now else None, "pull_shorts": (median(shorts) / subs_now) if shorts and subs_now else None,
            "engagement": (react / react_views) if react_views else None,
            "steadiness": (1 / (1 + cv)) if cv is not None else None,
            "cadence": (min(per_week, 14) * (0.5 + 0.5 * regular)) if regular is not None else (min(per_week, 14) * 0.5 if len(vs) >= 3 else None),
            "uploads_per_week": per_week, "staying": median(rates) if len(rates) >= 3 else None,
            "growth": ((s["last"][1] - s["first"][1]) / s["first"][1] * 7 / history) if history >= 3 and s.get("first") and s["first"][1] else None,
            "history_days": history,
        }
    reach_values = [r["reach"] for r in raw.values() if r["reach"] is not None]
    typical = median(reach_values) if len(reach_values) >= 4 else None  # the typical peer upload: the middle of the creators' median views
    for r in raw.values():
        if typical is not None and len(r["_mviews"]) >= 5:
            r["hitrate"] = sum(1 for x in r["_mviews"] if x >= typical) / len(r["_mviews"])
    peers = {k: [r[k] for r in raw.values() if r[k] is not None] for k in PARTS}
    risk = authenticity.scan(session, days=7, segment=segment, language=language, channel_ids=channel_ids, now=now) if with_authenticity and ids else {"channels": []}
    risk_by = {r["channel_id"]: r for r in risk["channels"]}
    rows = []
    for c in channels:
        r = raw[c.id]
        parts = {k: percentile_rank(r[k], peers[k]) for k in PARTS if r[k] is not None and len(peers[k]) >= 4}
        weight = sum(WEIGHTS[k] for k in parts)
        score = sum(WEIGHTS[k] * parts[k] for k in parts) / weight if weight else None
        pillars = {}
        for pillar in PILLARS:
            ks = [k for k in parts if PARTS[k][0] == pillar]
            pillars[pillar] = rnd(sum(WEIGHTS[k] * parts[k] for k in ks) / sum(WEIGHTS[k] for k in ks)) if ks else None
        # few uploads cap the confidence no matter how good the rest of the data is: 10 uploads are needed for full trust
        confidence = round(100 * min(1.0, r["videos"] / 10) * (0.55 + 0.15 * (1 if r["subscribers"] else 0) + 0.3 * min(1.0, r["history_days"] / 14)))
        rk = risk_by.get(c.id)
        confirmed = bool(rk and any(sig["review"] and sig["review"]["status"] == "confirmed" for sig in rk["signals"]))
        open_high = bool(rk and rk["risk"] == "high")
        raw_score = score
        if score is not None and open_high:
            score = max(0.0, score - 10)
        shown = None if (score is None or confirmed) else 50 + (score - 50) * confidence / 100
        strengths = [LABELS[k] for k, v in sorted(parts.items(), key=lambda kv: -kv[1]) if v >= 75][:2]
        watch = [LABELS[k] for k, v in sorted(parts.items(), key=lambda kv: kv[1]) if v < 25][:2]
        if shown is None:
            profile = "Not scored"
        elif confidence < 40:
            profile = "Emerging (little data)"
        elif parts.get("steadiness", 100) < 30 and parts.get("reach", 0) >= 60:
            profile = "Hit-driven"
        elif parts.get("growth", 0) >= 75:
            profile = "Rising"
        elif parts.get("steadiness", 0) >= 70:
            profile = "Steady"
        else:
            lead = max((v, k) for k, v in pillars.items() if v is not None) if any(v is not None for v in pillars.values()) else None
            spread = (max(v for v in pillars.values() if v is not None) - min(v for v in pillars.values() if v is not None)) if lead else 0
            profile = {"impact": "Impact-led", "followership": "Follower-led", "exposure": "Exposure-led"}[lead[1]] if lead and spread >= 20 else "Balanced"
        best = None
        if r["pull_video"] is not None and r["pull_shorts"] is not None:
            best = "Shorts" if r["pull_shorts"] > r["pull_video"] else "Videos"
        rows.append({
            "channel_id": c.id, "name": c.name, "segment": c.segment or "news", "language": languages[c.id], "index_score": rnd(shown), "raw_score": rnd(raw_score), "confidence": confidence,
            "confidence_label": "high" if confidence >= 70 else "medium" if confidence >= 40 else "low", "preliminary": confidence < 40, "profile": profile, "strengths": strengths, "watch": watch,
            "parts": {k: rnd(v) for k, v in parts.items()}, "pillars": pillars, "best_format": best, "subscribers": r["subscribers"], "uploads": r["videos"], "uploads_video": r["uploads_video"], "uploads_shorts": r["uploads_shorts"],
            "median_views": rnd(r["median_views"], 0), "pull_percent": rnd(r["pull"] * 100, 1) if r["pull"] is not None else None,
            "pull_video_percent": rnd(r["pull_video"] * 100, 1) if r["pull_video"] is not None else None, "pull_shorts_percent": rnd(r["pull_shorts"] * 100, 1) if r["pull_shorts"] is not None else None,
            "engagement_percent": rnd(r["engagement"] * 100, 2) if r["engagement"] is not None else None, "uploads_per_week": rnd(r["uploads_per_week"], 1),
            "best_upload_vs_subscribers_percent": rnd(r["bestshot"] * 100, 0) if r["bestshot"] is not None else None, "beyond_subscribers_percent": rnd(r["beyond"] * 100, 0) if r["beyond"] is not None else None,
            "momentum_percent": rnd((r["momentum"] - 1) * 100, 0) if r["momentum"] is not None else None, "early_pull_percent": rnd(r["earlypull"] * 100, 1) if r["earlypull"] is not None else None,
            "comments_per_1000_views": rnd(r["conversation"] * 1000, 1) if r["conversation"] is not None else None, "hit_rate_percent": rnd(r["hitrate"] * 100, 0) if r["hitrate"] is not None else None,
            "live_streams": r["live_streams"], "live_peak_median": rnd(r["live_peak_median"], 0), "days_since_last_upload": rnd(r["days_since_last_upload"], 1),
            "authenticity_risk": rk["risk"] if rk else "not_checked", "withheld_reason": "An admin confirmed unusual viewership for this channel." if confirmed else None,
        })
    rows.sort(key=lambda x: (x["index_score"] is not None, x["index_score"] or 0), reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank if row["index_score"] is not None else None
    note = None if len(channels) >= 5 else "Fewer than 5 creators are being compared, so the parts that are ranked against peers could not be scored."
    return {"index_name": INDEX_NAME, "days": days, "filters": {"segment": segment, "language": language}, "method": METHOD, "weights": WEIGHTS, "part_labels": LABELS, "tagline": TAGLINE, "pillar_names": PILLARS, "pillar_weights": PILLAR_WEIGHTS, "not_measured": NOT_MEASURED, "note": note,
            "generated_at": now.isoformat(), "channels": rows}
