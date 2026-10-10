"""Findings and briefings: the step that turns measured numbers into statements a person can act on.

The process STAXIS follows, and this module is step 4 and 5 of it:
  1 Collect    YouTube public data, every few minutes (collector)
  2 Verify     integrity checks and the authenticity radar (unusual patterns are flagged, never hidden)
  3 Measure    weekly views, prime-time audience, report builder, STX and the IFX Score
  4 Find       rules over the measurements produce findings: a headline, the numbers behind it, how sure we are, where to look next
  5 Brief      the same findings are put in front of different readers (media company, media buyer, campaign, creator, audience) with what each should do about it
  6 Report     a branded, machine-unreadable PDF that leads with the findings, then the tables, then the method
  7 Act        every finding links to the tool that lets you act on it (planner, audience, radar, report builder)
  8 Learn      an admin's decisions on flagged channels change what later reports say

A finding is never an opinion. Each one is a rule applied to measured numbers; it carries its evidence and a confidence, says plainly when data is thin, and never claims a cause that the data cannot show.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from api import authenticity
from api.market_common import latest_observations, mean, now_utc, parse_published, pick_channels, rnd, today_ist, utc
from api.market_tools import _videos_in, prime_time, weekly_views
from api.creator_index import creator_index
from collector.storage import Channel, Observation
from metrics.markets import market_label

PERSONAS = {
    "media": "Media company",
    "buyer": "Media buyer / advertiser",
    "politician": "Politician / campaign",
    "influencer": "Influencer / independent journalist",
    "audience": "Audience",
}
PROCESS = [
    ("Collect", "Public YouTube data is read every few minutes."),
    ("Verify", "Integrity checks and the authenticity radar flag anything unusual; flags are shown, not hidden."),
    ("Measure", "Weekly views, prime-time audience, report builder, STX and the IFX Score turn raw numbers into measures."),
    ("Find", "Rules over the measures produce findings with their evidence and a confidence."),
    ("Brief", "The same findings are shown to each kind of reader with what to do about them."),
    ("Report", "A branded PDF leads with the findings, then the tables, then how it was worked out."),
    ("Act", "Every finding links to the tool where you can act on it."),
    ("Learn", "An admin's decision on a flagged channel changes what later reports say."),
]
CONFIDENCE_ORDER = {"high": 3, "medium": 2, "low": 1}


def _f(fid: str, headline: str, detail: str, evidence: dict[str, Any], confidence: str, tool: str, tool_label: str, so_what: dict[str, str], weight: dict[str, int]) -> dict[str, Any]:
    return {"id": fid, "headline": headline, "detail": detail, "evidence": evidence, "confidence": confidence, "tool": tool, "tool_label": tool_label, "so_what": so_what,
            "personas": sorted(so_what), "weight": weight}


def _windows(days: int, now: datetime) -> tuple[str, str, str, str]:
    end = today_ist(now) - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    pend = start - timedelta(days=1)
    pstart = pend - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat(), pstart.isoformat(), pend.isoformat()


# -------------------------------------------------------------------------------------------- the rules
def _share_of_voice(session: Session, start: str, end: str, pstart: str, pend: str, segment: str | None, language: str | None, now: datetime, channel_ids: list[int] | None = None) -> list[dict[str, Any]]:
    cur = weekly_views(session, start_date=start, end_date=end, segment=segment, language=language, channel_ids=channel_ids, now=now)
    prev = weekly_views(session, start_date=pstart, end_date=pend, segment=segment, language=language, channel_ids=channel_ids, now=now)
    prev_by = {g["label"]: {c["channel_id"]: c for c in g["channels"]} for g in prev["groups"]}
    out = []
    for g in cur["groups"]:
        if len(g["channels"]) < 3 or not g["total_views"]:
            continue
        lead = g["channels"][0]
        before = (prev_by.get(g["label"]) or {}).get(lead["channel_id"])
        moves = []
        for c in g["channels"]:
            old = (prev_by.get(g["label"]) or {}).get(c["channel_id"])
            if old and old["share_percent"] is not None and c["share_percent"] is not None:
                moves.append((c["share_percent"] - old["share_percent"], c, old))
        up = max(moves, key=lambda m: m[0], default=None)
        down = min(moves, key=lambda m: m[0], default=None)
        change = f", {lead['share_percent'] - before['share_percent']:+.1f} points on the week before" if before and before["share_percent"] is not None else ""
        parts = [f"{lead['name']} took {lead['share_percent']}% of the views of videos uploaded in {g['label']}{change}."]
        if up and up[0] >= 2:
            parts.append(f"Biggest gain: {up[1]['name']} ({up[0]:+.1f} points).")
        if down and down[0] <= -2:
            parts.append(f"Biggest fall: {down[1]['name']} ({down[0]:+.1f} points).")
        measured = mean([c["coverage_percent"] for c in g["channels"] if c["coverage_percent"] is not None]) or 0
        conf = "high" if measured >= 80 and before else "medium" if measured >= 50 else "low"
        label = g["label"]
        out.append(_f(f"share-{label}", f"{lead['name']} leads {label} with {lead['share_percent']}% of views", " ".join(parts),
                      {"group": label, "from": start, "to": end, "leader": lead["name"], "share_percent": lead["share_percent"], "views": lead["views"], "total_views": g["total_views"],
                       "gain": {"name": up[1]["name"], "points": rnd(up[0])} if up else None, "fall": {"name": down[1]["name"], "points": rnd(down[0])} if down else None, "videos_measured_percent": rnd(measured)},
                      conf, "weekly", "Open the weekly report",
                      {"media": f"Your share of {label} is the number advertisers compare you on. Where you gained or lost points is where the audience moved.",
                       "buyer": f"{lead['name']} holds the biggest slice of {label} video views. Check its prime-time audience before you pay for a premium.",
                       "politician": f"{label} attention is concentrated: {lead['name']} has {lead['share_percent']}% of it. That is where a message reaches the most people.",
                       "influencer": f"The leader in {label} shows what a typical week's winning content looks like; compare your own views against it.",
                       "audience": f"Most people watching {label} videos last week were watching {lead['name']}."},
                      {"media": 90, "buyer": 80, "politician": 70, "influencer": 40, "audience": 50}))
    return out


def _prime(session: Session, start: str, end: str, segment: str | None, language: str | None, now: datetime, channel_ids: list[int] | None = None) -> list[dict[str, Any]]:
    pt = prime_time(session, start_date=start, end_date=end, language=language, segment=segment, channel_ids=channel_ids, now=now)
    slots = [s for s in pt["slots"] if s["top"]]
    if not slots:
        return []
    leaders = [(s["slot"], s["top"][0]) for s in slots]
    best_slot, best = max(leaders, key=lambda x: x[1]["average_concurrent"])
    second = next((r for r in next(s for s in slots if s["slot"] == best_slot)["channels"][1:2]), None)
    ratio = round(best["average_concurrent"] / second["average_concurrent"], 1) if second and second["average_concurrent"] else None
    distinct = []
    for slot, r in leaders:
        if not distinct or distinct[-1][1] != r["name"]:
            distinct.append([slot, r["name"]])
    peak_slot, peak = max(((s["slot"], max(s["channels"], key=lambda r: r["peak_concurrent"])) for s in slots), key=lambda x: x[1]["peak_concurrent"])
    days_in = best["days_in_range"]
    conf = "high" if best["days_seen"] >= max(4, days_in * 0.7) else "medium" if best["days_seen"] >= 3 else "low"
    out = [_f("prime-leader", f"{best['name']} has the biggest evening audience: about {best['average_concurrent']:,.0f} live viewers at {best_slot.replace('-', ' to ')}",
              (f"That is {ratio} times the next channel. " if ratio else "") + (("The leader changes through the evening: " + ", ".join(n + " from " + s.split("-")[0] for s, n in distinct) + ".") if len(distinct) > 1 else f"{best['name']} led every hour that was measured."),
              {"slot": best_slot, "leader": best["name"], "average": best["average_concurrent"], "ratio_to_second": ratio, "days_seen": best["days_seen"], "days_in_range": days_in, "leaders_by_hour": distinct},
              conf, "primetime", "Open prime time",
              {"media": "Your prime-time hours decide your ad rate card. If a rival leads an hour you pay for, that hour is where to put your strongest programme.",
               "buyer": f"Highest average audience per spot is at {best_slot.replace('-', ' to ')} on {best['name']}. Use the media planner to see what it costs per 1,000 viewers.",
               "politician": f"Evenings are when live audiences are largest ({best_slot.replace('-', ' to ')} is the peak hour). Schedule statements and live events for that window.",
               "audience": f"Most people are watching live news around {best_slot.replace('-', ' to ')}, mostly on {best['name']}."},
              {"media": 85, "buyer": 95, "politician": 80, "influencer": 20, "audience": 70})]
    out.append(_f("peak-moment", f"The highest single moment was {peak['peak_concurrent']:,.0f} viewers on {peak['name']} at {peak_slot.replace('-', ' to ')}",
                  f"The highest minute in any evening slot of these days. It is a peak, not an average: it shows what the channel can draw, not what it draws every night.",
                  {"channel": peak["name"], "peak": peak["peak_concurrent"], "slot": peak_slot, "average_in_that_slot": peak["average_concurrent"]}, conf, "primetime", "Open prime time",
                  {"media": "Peaks show your ceiling. The gap between your peak and your average is the audience you rented for a moment but did not keep.",
                   "buyer": "Do not buy on a peak. Price a spot on the average and treat the peak as upside.",
                   "politician": "Peaks happen around events. If your message is tied to a live moment, you are competing for that spike.",
                   "audience": f"The biggest live crowd was on {peak['name']}."},
                  {"media": 60, "buyer": 65, "politician": 60, "influencer": 15, "audience": 55}))
    return out


def _content_mix(session: Session, start: str, end: str, segment: str | None, language: str | None, now: datetime, channel_ids: list[int] | None = None) -> list[dict[str, Any]]:
    from api.market_common import ist_window, parse_day
    s0, e0 = ist_window(parse_day(start), parse_day(end))
    channels, languages = pick_channels(session, segment=segment, language=language, channel_ids=channel_ids)
    videos = _videos_in(session, [c.id for c in channels], s0, e0)
    latest = latest_observations(session, [v.id for v in videos])
    topic_views: dict[str, int] = defaultdict(int)
    kind_views = {"shorts": 0, "video": 0}
    kind_count = {"shorts": 0, "video": 0}
    for v in videos:
        o = latest.get(v.id)
        if o is None or o.view_count is None or o.classification in {"LIVE", "UPCOMING"}:
            continue
        topic_views[v.topic or "Other"] += int(o.view_count)
        k = "shorts" if o.classification == "SHORT" else "video"
        kind_views[k] += int(o.view_count)
        kind_count[k] += 1
    total = sum(topic_views.values())
    out = []
    if total and sum(kind_count.values()) >= 20:
        top = sorted(topic_views.items(), key=lambda kv: -kv[1])
        t1 = top[0]
        out.append(_f("genre-lead", f"{t1[0]} drew {100 * t1[1] / total:.0f}% of the views on new videos", "Genre is worked out from the video title; titles with no clear topic are counted under Other.",
                      {"genre": t1[0], "share_percent": rnd(100 * t1[1] / total), "mix": {k: rnd(100 * v / total) for k, v in top}, "videos": sum(kind_count.values()), "from": start, "to": end},
                      "high" if sum(kind_count.values()) >= 100 else "medium", "builder", "Cut it by genre in the report builder",
                      {"media": f"Audiences spent the most on {t1[0]}. Check whether your output matches where the views are.",
                       "buyer": f"Contextual placement: {t1[0]} content gets the largest share of attention. Brand fit matters more than the size alone.",
                       "politician": f"Politics drew {100 * topic_views.get('Politics', 0) / total:.0f}% of new-video views; {t1[0]} led. That is the share of attention public affairs competes for.",
                       "influencer": f"{t1[0]} is where the views are going. If it fits you, that is the crowded-but-rewarded lane; the others are where you can stand out.",
                       "audience": f"The most-watched kind of new video last week was {t1[0]}."},
                      {"media": 60, "buyer": 60, "politician": 85, "influencer": 80, "audience": 80}))
    kv_total = sum(kind_views.values())
    if kv_total and kind_count["shorts"] >= 10 and kind_count["video"] >= 10:
        sh = 100 * kind_views["shorts"] / kv_total
        per_s, per_v = kind_views["shorts"] / kind_count["shorts"], kind_views["video"] / kind_count["video"]
        out.append(_f("format-split", f"Shorts made {sh:.0f}% of the views on {kind_count['shorts'] + kind_count['video']:,} new uploads",
                      f"A Short averaged {per_s:,.0f} views and a video {per_v:,.0f}. Averages hide the winners: look at the IFX Score for who beats these.",
                      {"shorts_share_percent": rnd(sh), "shorts_count": kind_count["shorts"], "video_count": kind_count["video"], "average_views_short": rnd(per_s, 0), "average_views_video": rnd(per_v, 0)},
                      "high" if kind_count["shorts"] + kind_count["video"] >= 100 else "medium", "creators", "Open the IFX Score",
                      {"media": "If Shorts are a big share of new views and you publish few, you are absent from a format where attention is growing.",
                       "buyer": "Shorts and long videos are bought differently. Ask for the split before you accept a 'digital' package.",
                       "influencer": f"Shorts averaged {per_s:,.0f} views against {per_v:,.0f} for videos. Test both formats; the IFX Score 'best format' tag shows which one works for each creator.",
                       "politician": "Short clips travel on their own. A message that works in 30 seconds can reach people who never watch the full speech."},
                      {"media": 55, "buyer": 50, "politician": 55, "influencer": 90, "audience": 30}))
    return out


def _creators(session: Session, segment: str | None, language: str | None, now: datetime, channel_ids: list[int] | None = None) -> list[dict[str, Any]]:
    out = []
    for seg, label in (("creator", "creators and influencers"), ("journalist", "independent journalists"), ("commentator", "political commentators")):
        if segment and segment != seg:
            continue
        try:
            idx = creator_index(session, segment=seg, language=language, days=30, channel_ids=channel_ids, now=now, with_authenticity=False)
        except ValueError:
            continue
        scored = [r for r in idx["channels"] if r["index_score"] is not None]
        if len(scored) < 5:
            continue
        top = scored[0]
        rising = next((r for r in scored if r["profile"] == "Rising"), None)
        out.append(_f(f"creator-{seg}", f"{top['name']} tops the IFX Score for {label} at {top['index_score']:.0f}",
                      f"Profile: {top['profile']}. " + (f"Strong on {', '.join(top['strengths'])}. " if top["strengths"] else "") + (f"{rising['name']} is rising." if rising else ""),
                      {"group": seg, "top": top["name"], "index_score": top["index_score"], "confidence": top["confidence"], "profile": top["profile"], "rising": rising["name"] if rising else None, "compared": len(scored)},
                      top["confidence_label"], "creators", "Open the IFX Score",
                      {"influencer": f"This is the benchmark in your group. The pillar you are weakest on (Impact, Followership or eXposure) shows where to work.",
                       "buyer": f"For a creator campaign, {top['name']} scores best, but read the profile: '{top['profile']}' tells you whether results are steady or hit-driven.",
                       "politician": f"Among {label}, {top['name']} has the strongest mix of reach, reaction and regularity. Compare before choosing a messenger.",
                       "media": f"Independent voices are competing for your audience. {top['name']} is the one to watch in {label}."},
                      {"media": 50, "buyer": 70, "politician": 75, "influencer": 95, "audience": 20}))
    return out


def _authenticity(session: Session, segment: str | None, language: str | None, now: datetime, channel_ids: list[int] | None = None) -> list[dict[str, Any]]:
    scan = authenticity.scan(session, days=7, segment=segment, language=language, channel_ids=channel_ids, now=now, use_cache=False)
    s = scan["summary"]
    flagged = [c for c in scan["channels"] if c["risk"] in ("high", "review")]
    if not flagged:
        return [_f("authenticity-clear", "No channel shows an unusual viewership pattern this week", "The radar checked likes per view, view bursts, live spikes, flat lines and identical steps.",
                   {"checked": len(scan["channels"]), "summary": s}, "medium", "authenticity", "Open the authenticity radar",
                   {"buyer": "Nothing unusual was flagged, so the audiences in this brief can be compared at face value.", "media": "Your numbers show no pattern that would raise a buyer's question.",
                    "politician": "No unusual patterns were flagged in the channels you would be using.", "influencer": "No unusual pattern was flagged; clean numbers are a selling point."},
                   {"media": 30, "buyer": 60, "politician": 30, "influencer": 40, "audience": 10})]
    names = ", ".join(c["name"] for c in flagged[:3])
    return [_f("authenticity-flags", f"{s['high']} channel(s) to review now and {s['review']} to check", f"Flagged: {names}. A flag is an unusual pattern, not proof; an admin reviews the evidence.",
               {"summary": s, "channels": [{"name": c["name"], "risk": c["risk"], "signals": [x["title"] for x in c["signals"]]} for c in flagged[:8]]}, "medium", "authenticity", "Open the authenticity radar",
               {"buyer": "Do not buy a flagged channel until the pattern is explained. The media planner already skips high-risk channels in its budget split.",
                "media": "If your own channel is flagged, ask your account manager for the evidence; a cleared flag is recorded and stops counting against you.",
                "politician": "Reach figures from a flagged channel may not be real attention. Verify before you rely on them.",
                "influencer": "If you are flagged, the evidence shows which pattern looked unusual; an admin can clear it with a note once it is explained."},
               {"media": 75, "buyer": 90, "politician": 60, "influencer": 70, "audience": 15})]


def _health(session: Session, now: datetime) -> dict[str, Any]:
    last = session.query(func.max(Observation.observed_at)).scalar()
    age = (now - utc(last)).total_seconds() / 60 if last else None
    n = session.query(Channel).filter(Channel.active.is_(True)).count()
    return {"channels": n, "last_measurement_minutes_ago": rnd(age, 0)}


def briefing_as_report(b: dict[str, Any]) -> dict[str, Any]:
    """The shape the PDF writer takes: a briefing is a report whose body is findings instead of a ranking table."""
    return {"kind": "briefing", "scope": "briefing", "scope_label": "Briefing", "title": f"Briefing for {b['persona_label'].lower()}", "feed": None, "genre": None, "from": b["window"]["from"], "to": b["window"]["to"],
            "start_hour": 0, "end_hour": 24, "filters": b["filters"], "generated_at": b["generated_at"], "rows": [], "by_genre": [], "coverage": {}, "persona": b["persona"], "briefing": b,
            "method": "Every finding is a rule applied to measured YouTube public data, with the numbers behind it and a confidence. A finding states what the data shows, never why it happened. "
                      "Views are not TV ratings and audiences of different channels overlap by an amount that is not visible here."}


# -------------------------------------------------------------------------------------------- the briefing
def briefing(session: Session, *, persona: str, days: int = 7, segment: str | None = None, language: str | None = None, channel_ids: list[int] | None = None, now: datetime | None = None, limit: int = 8) -> dict[str, Any]:
    if persona not in PERSONAS:
        raise ValueError("persona must be one of: " + ", ".join(PERSONAS))
    if not 3 <= int(days) <= 28:
        raise ValueError("days must be between 3 and 28")
    days = int(days)
    now = utc(now) if now else now_utc()
    start, end, pstart, pend = _windows(days, now)
    found: list[dict[str, Any]] = []
    for rule in (lambda: _share_of_voice(session, start, end, pstart, pend, segment, language, now, channel_ids), lambda: _prime(session, start, end, segment, language, now, channel_ids),
                 lambda: _content_mix(session, start, end, segment, language, now, channel_ids), lambda: _creators(session, segment, language, now, channel_ids), lambda: _authenticity(session, segment, language, now, channel_ids)):
        try:
            found.extend(rule())
        except ValueError:
            continue
    mine = [f for f in found if persona in f["so_what"]]
    mine.sort(key=lambda f: (-f["weight"][persona], -CONFIDENCE_ORDER[f["confidence"]]))
    items = [{"id": f["id"], "headline": f["headline"], "detail": f["detail"], "evidence": f["evidence"], "confidence": f["confidence"], "tool": f["tool"], "tool_label": f["tool_label"],
              "so_what": f["so_what"][persona]} for f in mine[:limit]]
    health = _health(session, now)
    kpis = []
    for f in mine:
        ev = f["evidence"]
        if f["id"].startswith("share-") and len(kpis) < 2:
            kpis.append({"label": f"{ev['group']} leader", "value": f"{ev['share_percent']}%", "detail": ev["leader"]})
        elif f["id"] == "prime-leader":
            kpis.append({"label": "Biggest evening audience", "value": f"{ev['average']:,.0f}", "detail": f"{ev['leader']}, {ev['slot'].replace('-', ' to ')}"})
        elif f["id"] == "format-split":
            kpis.append({"label": "Shorts share of new views", "value": f"{ev['shorts_share_percent']}%", "detail": f"{ev['shorts_count']} Shorts, {ev['video_count']} videos"})
        elif f["id"] == "genre-lead":
            kpis.append({"label": "Most-watched genre", "value": ev["genre"], "detail": f"{ev['share_percent']}% of new-video views"})
    kpis.append({"label": "Channels measured", "value": str(health["channels"]), "detail": f"last measurement {health['last_measurement_minutes_ago']:.0f} min ago" if health["last_measurement_minutes_ago"] is not None else "no measurement yet"})
    reports = {"media": [("Weekly views by group", "weekly"), ("Prime-time league", "primetime"), ("Report builder PDF", "builder")],
               "buyer": [("Media planner", "planner"), ("Audience geography and age", "audience"), ("Authenticity radar", "authenticity"), ("Report builder PDF", "builder")],
               "politician": [("Report builder by genre", "builder"), ("Prime-time league", "primetime"), ("Audience geography and age", "audience")],
               "influencer": [("IFX Score", "creators"), ("Weekly report", "weekly"), ("Report builder PDF", "builder")],
               "audience": [("Prime time", "primetime"), ("Weekly report", "weekly")]}[persona]
    return {"persona": persona, "persona_label": PERSONAS[persona], "days": days, "window": {"from": start, "to": end, "previous_from": pstart, "previous_to": pend, "timezone": "IST"},
            "filters": {"segment": segment, "language": language, "channel_ids": channel_ids or []}, "generated_at": now.isoformat(), "kpis": kpis[:5], "findings": items, "recommended": [{"label": a, "tool": b} for a, b in reports],
            "process": [{"step": i + 1, "name": n, "what": w} for i, (n, w) in enumerate(PROCESS)], "health": health,
            "note": None if items else "There is not enough measured data yet in these days to state a finding. Nothing is estimated."}
