"""Facebook, Instagram and X beside YouTube: who has how many followers, how fast each is growing, how people react to what is posted, and which posts did best.

Every figure is a public figure of a public account, read through the platform's official API or supplied by a sheet or an administrator, and each row says when it was read. Nothing is guessed:
  * growth compares the newest reading with the newest reading at or before the start of the window; if the history is shorter than the window the span actually used is shown, and under one day there is no growth;
  * the engagement rate is (likes + comments + shares) per post, averaged over the posts of the window that have a figure, as a percentage of the followers. Reach and impressions are not public, so this is
    "how many people reacted", not "how many people saw it"; a rate worked out from fewer than 5 posts is marked low-confidence;
  * a figure the platform does not give (Instagram shares, Facebook views ...) is left out, never counted as zero;
  * followers of different platforms are added up as "social followers", which counts a person who follows a channel on two platforms twice. It is a size of presence, not a count of people.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from api.market_common import IST, pick_channels, rnd
from collector.social import settings as social_settings
from collector.social.base import PLATFORM_LABEL
from collector.storage import Channel, ChannelStats, SocialAccount, SocialPost, SocialPostStats, SocialStats, SOCIAL_PLATFORMS

METHOD = ("Followers are the public follower count of each account at the time it was read (Facebook page followers, Instagram followers, X followers). Growth compares the newest reading with the newest reading "
          "at or before the start of the chosen period; when we have been reading for less time than the period, the shorter span is shown and under one day there is no growth. The engagement rate is the "
          "likes, comments and shares of the account's posts in the period, averaged per post, as a percentage of the followers. Reach and impressions are not public, so this says how many people reacted, "
          "not how many saw the post. A figure a platform does not give is left out, never counted as zero. Social followers add the platforms together and count a person who follows on two platforms twice.")
LOW_SAMPLE = 5


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value else None


def _readings_upto(session: Session, ids: list[int], when: datetime) -> dict[int, SocialStats]:
    """For each account, its newest reading with a followers figure at or before ``when``."""
    out: dict[int, SocialStats] = {}
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        newest = (session.query(SocialStats.account_id.label("a"), func.max(SocialStats.observed_at).label("m"))
                  .filter(SocialStats.account_id.in_(chunk), SocialStats.observed_at <= when, SocialStats.followers.isnot(None)).group_by(SocialStats.account_id).subquery())
        for row in session.query(SocialStats).join(newest, (SocialStats.account_id == newest.c.a) & (SocialStats.observed_at == newest.c.m)):
            out[row.account_id] = row
    return out


def _first_readings(session: Session, ids: list[int]) -> dict[int, SocialStats]:
    out: dict[int, SocialStats] = {}
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        oldest = (session.query(SocialStats.account_id.label("a"), func.min(SocialStats.observed_at).label("m"))
                  .filter(SocialStats.account_id.in_(chunk), SocialStats.followers.isnot(None)).group_by(SocialStats.account_id).subquery())
        for row in session.query(SocialStats).join(oldest, (SocialStats.account_id == oldest.c.a) & (SocialStats.observed_at == oldest.c.m)):
            out[row.account_id] = row
    return out


def _post_figures(session: Session, ids: list[int], since: datetime) -> dict[int, list[dict[str, Any]]]:
    """For each account: its posts since ``since`` with the newest figures of each."""
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if not ids:
        return out
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        posts = session.query(SocialPost).filter(SocialPost.account_id.in_(chunk), SocialPost.posted_at >= since).all()
        by_id = {p.id: p for p in posts}
        if not by_id:
            continue
        pids = list(by_id)
        for j in range(0, len(pids), 400):
            part = pids[j:j + 400]
            newest = session.query(SocialPostStats.post_id.label("p"), func.max(SocialPostStats.observed_at).label("m")).filter(SocialPostStats.post_id.in_(part)).group_by(SocialPostStats.post_id).subquery()
            latest = {s.post_id: s for s in session.query(SocialPostStats).join(newest, (SocialPostStats.post_id == newest.c.p) & (SocialPostStats.observed_at == newest.c.m))}
            for pid in part:
                p, s = by_id[pid], latest.get(pid)
                figures = [v for v in ((s.likes, s.comments, s.shares) if s else ()) if v is not None]
                out[p.account_id].append({"post": p, "likes": s.likes if s else None, "comments": s.comments if s else None, "shares": s.shares if s else None, "views": s.views if s else None,
                                          "interactions": sum(figures) if figures else None, "observed_at": s.observed_at if s else None})
    return out


def _youtube_subscribers(session: Session, channel_ids: list[int]) -> dict[int, int | None]:
    out: dict[int, int | None] = {}
    for i in range(0, len(channel_ids), 400):
        chunk = channel_ids[i:i + 400]
        newest = session.query(ChannelStats.channel_id.label("c"), func.max(ChannelStats.observed_at).label("m")).filter(ChannelStats.channel_id.in_(chunk), ChannelStats.subscribers.isnot(None)).group_by(ChannelStats.channel_id).subquery()
        for row in session.query(ChannelStats).join(newest, (ChannelStats.channel_id == newest.c.c) & (ChannelStats.observed_at == newest.c.m)):
            out[row.channel_id] = row.subscribers
    return out


def _growth(latest: SocialStats | None, base: SocialStats | None, days: int) -> dict[str, Any]:
    if latest is None or base is None or base.id == latest.id or latest.followers is None or base.followers is None:
        return {"growth_abs": None, "growth_pct": None, "growth_span_days": None}
    span = (_utc(latest.observed_at) - _utc(base.observed_at)).total_seconds() / 86400
    if span < 1:
        return {"growth_abs": None, "growth_pct": None, "growth_span_days": None}
    change = latest.followers - base.followers
    return {"growth_abs": change, "growth_pct": rnd(change / base.followers * 100, 2) if base.followers > 0 else None, "growth_span_days": round(span, 1)}


def _engagement(figures: list[dict[str, Any]], followers: int | None) -> dict[str, Any]:
    measured = [f for f in figures if f["interactions"] is not None]
    if not measured:
        return {"posts_in_period": len(figures), "posts_measured": 0, "avg_interactions": None, "engagement_rate": None, "low_sample": True}
    avg = sum(f["interactions"] for f in measured) / len(measured)
    return {"posts_in_period": len(figures), "posts_measured": len(measured), "avg_interactions": rnd(avg, 1),
            "engagement_rate": rnd(avg / followers * 100, 3) if followers else None, "low_sample": len(measured) < LOW_SAMPLE}


def account_rows(session: Session, *, platform: str | None = None, language: str | None = None, segment: str | None = None, days: int = 30, now: datetime | None = None,
                 channel_ids: list[int] | None = None) -> list[dict[str, Any]]:
    """One row for each linked account of the chosen channels: followers, growth, engagement, and when it was read."""
    now = _utc(now or datetime.now(UTC))
    days = max(1, min(int(days), 365))
    channels, languages = pick_channels(session, segment=segment, language=language, channel_ids=channel_ids)
    by_channel = {c.id: c for c in channels}
    if not by_channel:
        return []
    query = session.query(SocialAccount).filter(SocialAccount.channel_id.in_(list(by_channel)), SocialAccount.active.is_(True))
    if platform:
        query = query.filter(SocialAccount.platform == platform)
    accounts = query.order_by(SocialAccount.id).all()
    ids = [a.id for a in accounts]
    latest = _readings_upto(session, ids, now)
    window_start = now - timedelta(days=days)
    base = _readings_upto(session, ids, window_start)
    first = _first_readings(session, ids)
    posts = _post_figures(session, ids, window_start)
    rows = []
    for a in accounts:
        last = latest.get(a.id)
        started = base.get(a.id) or first.get(a.id)
        ch = by_channel[a.channel_id]
        row = {"account_id": a.id, "channel_id": ch.id, "channel": ch.name, "language": languages.get(ch.id), "segment": ch.segment, "platform": a.platform, "platform_label": PLATFORM_LABEL[a.platform],
               "handle": a.handle, "display_name": a.display_name, "url": a.url, "followers": last.followers if last else None, "following": last.following if last else None,
               "posts_total": last.posts_total if last else None, "observed_at": _iso(last.observed_at) if last else None, "source": last.source if last else None,
               "status": a.last_status, "history_days": round((_utc(last.observed_at) - _utc(first[a.id].observed_at)).total_seconds() / 86400, 1) if last and a.id in first else None}
        row.update(_growth(last, started, days))
        row.update(_engagement(posts.get(a.id, []), last.followers if last else None))
        rows.append(row)
    return rows


SORTS = {"followers": lambda r: r["followers"], "growth": lambda r: r["growth_pct"], "growth_abs": lambda r: r["growth_abs"], "engagement": lambda r: r["engagement_rate"], "posts": lambda r: r["posts_in_period"]}


def overview(session: Session, *, platform: str | None = None, language: str | None = None, segment: str | None = None, days: int = 30, sort: str = "followers", now: datetime | None = None) -> dict[str, Any]:
    """The rankings: for each platform, the accounts ranked by the chosen measure, with the platform's totals; and how much of the market has an account linked."""
    now = _utc(now or datetime.now(UTC))
    if platform and platform not in SOCIAL_PLATFORMS:
        raise ValueError("the platform must be facebook, instagram or x")
    if sort not in SORTS:
        raise ValueError("sort must be followers, growth, growth_abs, engagement or posts")
    days = max(1, min(int(days), 365))
    rows = account_rows(session, platform=platform, language=language, segment=segment, days=days, now=now)
    platforms = []
    for key in SOCIAL_PLATFORMS:
        if platform and key != platform:
            continue
        mine = [r for r in rows if r["platform"] == key]
        have = [r for r in mine if r["followers"] is not None]
        ranked = sorted(have, key=lambda r: (SORTS[sort](r) is None, -(SORTS[sort](r) or 0), r["channel"].lower()))
        ranked += sorted((r for r in mine if r["followers"] is None), key=lambda r: r["channel"].lower())
        for n, r in enumerate(ranked, start=1):
            r["rank"] = n if r["followers"] is not None and SORTS[sort](r) is not None else None
        grown = [r for r in have if r["growth_abs"] is not None]
        rates = [r["engagement_rate"] for r in have if r["engagement_rate"] is not None and not r["low_sample"]]
        total = sum(r["followers"] for r in have)
        base_total = sum(r["followers"] - r["growth_abs"] for r in grown)
        platforms.append({"platform": key, "label": PLATFORM_LABEL[key], "accounts": len(mine), "with_data": len(have), "followers_total": total if have else None,
                          "growth_abs_total": sum(r["growth_abs"] for r in grown) if grown else None, "growth_pct_total": rnd(sum(r["growth_abs"] for r in grown) / base_total * 100, 2) if grown and base_total > 0 else None,
                          "average_engagement_rate": rnd(sum(rates) / len(rates), 3) if rates else None, "rows": ranked})
    channels, _ = pick_channels(session, segment=segment, language=language)
    linked = {r["channel_id"] for r in rows}
    return {"as_of": now.isoformat(), "days": days, "sort": sort, "platform": platform, "platforms": platforms,
            "coverage": {"channels": len(channels), "channels_with_an_account": len(linked), "accounts": len(rows), "accounts_with_data": sum(1 for r in rows if r["followers"] is not None)},
            "method": METHOD}


def presence(session: Session, *, language: str | None = None, segment: str | None = None, days: int = 30, now: datetime | None = None) -> dict[str, Any]:
    """Every channel on one row: YouTube subscribers and the followers on each platform, with the total and the growth of the total."""
    now = _utc(now or datetime.now(UTC))
    rows = account_rows(session, language=language, segment=segment, days=days, now=now)
    channels, languages = pick_channels(session, segment=segment, language=language)
    subs = _youtube_subscribers(session, [c.id for c in channels])
    by_channel: dict[int, dict[str, Any]] = {}
    for c in channels:
        by_channel[c.id] = {"channel_id": c.id, "channel": c.name, "language": languages.get(c.id), "segment": c.segment, "youtube": subs.get(c.id), "facebook": None, "instagram": None, "x": None, "growth_abs": None, "accounts": 0}
    for r in rows:
        item = by_channel.get(r["channel_id"])
        if item is None:
            continue
        item["accounts"] += 1
        if r["followers"] is not None:
            item[r["platform"]] = (item[r["platform"]] or 0) + r["followers"]
        if r["growth_abs"] is not None:
            item["growth_abs"] = (item["growth_abs"] or 0) + r["growth_abs"]
    out = []
    for item in by_channel.values():
        parts = [item[k] for k in ("youtube", "facebook", "instagram", "x") if item[k] is not None]
        item["total"] = sum(parts) if parts else None
        item["platforms_covered"] = len(parts)
        out.append(item)
    out.sort(key=lambda r: (r["total"] is None, -(r["total"] or 0), r["channel"].lower()))
    for n, r in enumerate(out, start=1):
        r["rank"] = n if r["total"] is not None else None
    try:
        from api.stx_attach import attach, stx_map
        attach(out, stx_map(session, now=now))
    except Exception:   # the ranking is still true without the STX column
        for r in out:
            r.setdefault("stx", None)
    return {"as_of": now.isoformat(), "days": max(1, min(int(days), 365)), "rows": out, "note": "YouTube subscribers and the followers on Facebook, Instagram and X are added up as 'social followers'. A person who follows a channel on two platforms is counted twice.", "method": METHOD}


def _daily_series(session: Session, account_ids: list[int], since: datetime, now: datetime) -> dict[int, list[dict[str, Any]]]:
    """For each account: its last reading of each Indian day since ``since``."""
    series: dict[int, dict[Any, SocialStats]] = defaultdict(dict)
    for i in range(0, len(account_ids), 200):
        for s in (session.query(SocialStats).filter(SocialStats.account_id.in_(account_ids[i:i + 200]), SocialStats.observed_at >= since, SocialStats.observed_at <= now, SocialStats.followers.isnot(None))
                  .order_by(SocialStats.observed_at)):
            series[s.account_id][(_utc(s.observed_at) + IST.utcoffset(None)).date()] = s
    return {a: [{"observed_at": _iso(s.observed_at), "value": s.followers, "day": d.isoformat()} for d, s in sorted(days.items())] for a, days in series.items()}


def channel_social(session: Session, channel_id: int, *, days: int = 90, now: datetime | None = None) -> dict[str, Any]:
    """One channel on every platform: its accounts, the follower history of each, its best posts and when its posts do best."""
    now = _utc(now or datetime.now(UTC))
    days = max(7, min(int(days), 365))
    channel = session.get(Channel, channel_id)
    if channel is None:
        raise LookupError("that channel does not exist")
    rows = account_rows(session, days=min(days, 30), now=now, channel_ids=[channel_id])
    ids = [r["account_id"] for r in rows]
    series = _daily_series(session, ids, now - timedelta(days=days), now)
    for r in rows:
        r["series"] = series.get(r["account_id"], [])
    figures = _post_figures(session, ids, now - timedelta(days=days))
    handle = {r["account_id"]: r for r in rows}
    best, hours = [], defaultdict(lambda: [0, 0.0, 0])
    for aid, items in figures.items():
        for f in items:
            p = f["post"]
            if f["interactions"] is not None:
                best.append(_post_row(p, f, handle[aid], channel))
                if p.posted_at:
                    h = (_utc(p.posted_at).astimezone(IST)).hour
                    hours[h][0] += 1
                    hours[h][1] += f["interactions"]
                    hours[h][2] += 1
    best.sort(key=lambda r: -(r["interactions"] or 0))
    by_hour = [{"hour": h, "posts": v[0], "average_interactions": rnd(v[1] / v[2], 1) if v[2] else None} for h, v in sorted(hours.items())]
    post_count = sum(len(v) for v in figures.values())
    yt = session.query(ChannelStats).filter(ChannelStats.channel_id == channel_id, ChannelStats.observed_at >= now - timedelta(days=days), ChannelStats.subscribers.isnot(None)).order_by(ChannelStats.observed_at).all()
    daily_yt: dict[Any, ChannelStats] = {}
    for s in yt:
        daily_yt[(_utc(s.observed_at) + IST.utcoffset(None)).date()] = s
    return {"channel_id": channel.id, "channel": channel.name, "language": channel.language, "segment": channel.segment, "days": days, "as_of": now.isoformat(), "accounts": rows,
            "youtube": {"subscribers": _youtube_subscribers(session, [channel.id]).get(channel.id), "series": [{"observed_at": _iso(s.observed_at), "value": s.subscribers, "day": d.isoformat()} for d, s in sorted(daily_yt.items())]},
            "top_posts": best[:15], "posts_in_period": post_count, "posts_per_week": rnd(post_count / (days / 7), 1) if post_count else None, "by_hour": by_hour, "method": METHOD}


def _post_row(p: SocialPost, f: dict[str, Any], account: dict[str, Any], channel: Channel | None = None) -> dict[str, Any]:
    followers = account.get("followers")
    return {"post_id": p.id, "channel_id": account["channel_id"], "channel": account["channel"], "platform": account["platform"], "platform_label": account["platform_label"], "handle": account["handle"],
            "text": p.text, "permalink": p.permalink, "media_type": p.media_type, "posted_at": _iso(p.posted_at), "likes": f["likes"], "comments": f["comments"], "shares": f["shares"], "views": f["views"],
            "interactions": f["interactions"], "rate": rnd(f["interactions"] / followers * 100, 3) if f["interactions"] is not None and followers else None, "observed_at": _iso(f["observed_at"])}


def top_posts(session: Session, *, platform: str | None = None, language: str | None = None, segment: str | None = None, days: int = 7, limit: int = 30, sort: str = "interactions",
              now: datetime | None = None) -> dict[str, Any]:
    now = _utc(now or datetime.now(UTC))
    days = max(1, min(int(days), 90))
    limit = max(1, min(int(limit), 100))
    if sort not in ("interactions", "views", "rate"):
        raise ValueError("sort must be interactions, views or rate")
    rows = account_rows(session, platform=platform, language=language, segment=segment, days=days, now=now)
    by_account = {r["account_id"]: r for r in rows}
    out = []
    for aid, items in _post_figures(session, list(by_account), now - timedelta(days=days)).items():
        for f in items:
            if f["interactions"] is not None or f["views"] is not None:
                out.append(_post_row(f["post"], f, by_account[aid]))
    key = {"interactions": lambda r: r["interactions"], "views": lambda r: r["views"], "rate": lambda r: r["rate"]}[sort]
    out = sorted((r for r in out if key(r) is not None), key=lambda r: -key(r))[:limit]
    for n, r in enumerate(out, start=1):
        r["rank"] = n
    return {"as_of": now.isoformat(), "days": days, "sort": sort, "platform": platform, "posts": out,
            "note": "Likes, comments and shares are what the platform shows publicly for each post. Views are shown only where the platform gives them (X does; Instagram and Facebook do not for other people's accounts). Reach is not public."}


def compare(session: Session, channel_ids: list[int], *, platform: str, days: int = 30, now: datetime | None = None) -> dict[str, Any]:
    """Several channels on one platform side by side: followers now, growth, engagement and the follower history of each."""
    if platform not in SOCIAL_PLATFORMS:
        raise ValueError("the platform must be facebook, instagram or x")
    if not channel_ids:
        raise ValueError("choose at least one channel")
    if len(channel_ids) > 12:
        raise ValueError("compare at most 12 channels at a time")
    now = _utc(now or datetime.now(UTC))
    days = max(7, min(int(days), 365))
    rows = account_rows(session, platform=platform, days=min(days, 30), now=now, channel_ids=channel_ids)
    series = _daily_series(session, [r["account_id"] for r in rows], now - timedelta(days=days), now)
    for r in rows:
        r["series"] = series.get(r["account_id"], [])
    rows.sort(key=lambda r: (r["followers"] is None, -(r["followers"] or 0)))
    return {"as_of": now.isoformat(), "days": days, "platform": platform, "rows": rows, "method": METHOD}


def report_block(session: Session, *, language: str | None = None, segment: str | None = None, days: int = 30, now: datetime | None = None) -> dict[str, Any] | None:
    """The social-media part of a periodic report: for each platform the five biggest accounts of the market and the platform's total, with growth over the period. None when no account has a figure yet."""
    data = overview(session, language=language, segment=segment, days=max(7, min(int(days), 365)), now=now)
    platforms = []
    for p in data["platforms"]:
        have = [r for r in p["rows"] if r["followers"] is not None]
        if have:
            platforms.append({"platform": p["label"], "total": p["followers_total"], "growth_pct": p["growth_pct_total"], "accounts": len(have),
                              "top": [{"name": r["channel"], "handle": r["handle"], "followers": r["followers"], "growth_pct": r["growth_pct"]} for r in have[:5]]})
    if not platforms:
        return None
    return {"days": data["days"], "platforms": platforms, "note": "Public follower counts read through each platform's official API or supplied by the channel; growth compares the newest reading with the one at the start of the period. Not part of the STX Index."}


def coverage(session: Session) -> dict[str, Any]:
    """How much of the market has accounts linked and how many of them have been read: shown to administrators and in the data-completeness view."""
    channels = session.query(func.count(Channel.id)).filter(Channel.active.is_(True)).scalar() or 0
    accounts = session.query(SocialAccount).all()
    with_data = {aid for (aid,) in session.query(SocialStats.account_id).filter(SocialStats.followers.isnot(None)).distinct()}
    by_platform = {}
    for key in SOCIAL_PLATFORMS:
        mine = [a for a in accounts if a.platform == key]
        by_platform[key] = {"label": PLATFORM_LABEL[key], "accounts": len(mine), "active": sum(1 for a in mine if a.active), "with_data": sum(1 for a in mine if a.id in with_data),
                            "failing": sum(1 for a in mine if a.active and a.last_status not in (None, "ok", "not_configured")), "no_key": sum(1 for a in mine if a.active and a.last_status == "not_configured")}
    last = max((_utc(a.last_ok_at) for a in accounts if a.last_ok_at), default=None)
    return {"channels": channels, "channels_with_an_account": len({a.channel_id for a in accounts}), "accounts": len(accounts), "accounts_with_data": len(with_data), "by_platform": by_platform,
            "last_read_at": _iso(last), "settings": social_settings.public_status(session)}
