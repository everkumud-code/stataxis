"""The data behind the public demo: a small, plainly invented set of channels and a week of invented viewer numbers, in a database that lives only in memory.

The demo runs the real StatAxis screens and the real calculations on this data, so what a visitor sees is how the product behaves. Nothing here is a real channel, a real audience or a real
measurement: every name says "Sample", every audience profile says so, and the numbers come from a fixed random seed. The data is rebuilt around the current time, so "now" is always now.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert
from sqlalchemy.orm import Session

from api import audience
from api.auth import hash_password
from collector.storage import Channel, ChannelStats, Observation, SocialAccount, SocialPost, SocialPostStats, SocialStats, User, UserPref, Video

DEMO_LOGIN = "demo@stataxis.org"
DEMO_USER_ID = 2_000_000_001   # no real account can have this number, so a demo session token can never be used as a real login
IST = timedelta(hours=5, minutes=30)
TITLES = ["Budget day live: markets react", "Election result live updates", "Cricket live: the decisive over", "Studio debate: the week in politics", "Breaking: storm warning for the coast",
          "Union Budget special: what changes for you", "Parliament live: the opposition walks out", "Markets live: the closing bell"]
TOPICS = ["Politics", "Sports", "Entertainment", "Business", "Current Affairs", "Other"]

NEWS = [("Sample News A", "Hindi", 52_000), ("Sample News B", "Hindi", 38_000), ("Sample News C", "Hindi", 30_000), ("Sample News D", "Hindi", 21_000), ("Sample News E", "Hindi", 15_000),
        ("Sample News F", "Hindi", 11_000), ("Sample News G", "Hindi", 7_500), ("Sample News H", "Hindi", 5_500), ("Sample English A", "English", 14_000), ("Sample English B", "English", 8_500),
        ("Sample English C", "English", 4_500), ("Sample Tamil A", "Tamil", 9_000), ("Sample Tamil B", "Tamil", 4_000)]
BUSINESS = [("Sample Business A", "English", 6_000), ("Sample Business B", "Hindi", 3_500)]
CREATORS = [("Sample Creator A", "creator", 420_000), ("Sample Creator B", "creator", 260_000), ("Sample Creator C", "creator", 150_000), ("Sample Creator D", "creator", 90_000),
            ("Sample Journalist A", "journalist", 310_000), ("Sample Journalist B", "journalist", 120_000)]
FLAT = "Sample News H"   # its live audience never moves: the authenticity radar has something to show


def _evening_curve(hour_ist: float) -> float:
    """Audience through an Indian day: a quiet night, a morning bump, and the big evening."""
    return 0.18 + 0.30 * math.exp(-((hour_ist - 9.5) ** 2) / 6) + 0.95 * math.exp(-((hour_ist - 21.0) ** 2) / 5) + 0.25 * math.exp(-((hour_ist - 13.5) ** 2) / 8)


def seed(session: Session, now: datetime | None = None, *, days: int = 8, seed_value: int = 11) -> dict[str, int]:
    """Fill an empty database with the invented channels and a week of invented numbers up to ``now``."""
    rnd = random.Random(seed_value)
    now = (now or datetime.now(UTC)).astimezone(UTC).replace(second=0, microsecond=0)
    session.add(User(id=DEMO_USER_ID, email=DEMO_LOGIN, password_hash=hash_password("demo-" + "x" * 24), plan="sx_enterprise", requested_plan="sx_enterprise", is_admin=False, active=True, approval_status="approved",
                     full_name="Demo visitor", organization="StatAxis demo"))
    session.flush()
    session.add(UserPref(user_id=session.query(User).filter_by(email=DEMO_LOGIN).one().id, onboarded_at=now))   # the demo shows every screen and does not ask who the visitor is
    channels: list[Channel] = []
    for i, (name, language, _base) in enumerate(NEWS):
        channels.append(Channel(youtube_channel_id=f"UCdemo{i:02d}" + "x" * 16, name=name, network="Sample", language=language, region="India", segment="news", active=True, handle=f"@sample{i}"))
    for i, (name, language, _base) in enumerate(BUSINESS):
        channels.append(Channel(youtube_channel_id=f"UCbiz{i:02d}" + "x" * 17, name=name, network="Sample", language=language, region="India", segment="business", active=True, handle=f"@samplebiz{i}"))
    for i, (name, segment, _base) in enumerate(CREATORS):
        channels.append(Channel(youtube_channel_id=f"UCcre{i:02d}" + "x" * 17, name=name, network="Sample", language="Hindi", region="India", segment=segment, active=True, handle=f"@samplecreator{i}"))
    session.add_all(channels)
    session.flush()
    by_name = {c.name: c for c in channels}

    # ---- live streams: one primary feed per news and business channel, sampled every two minutes for the whole period
    rows: list[dict] = []
    live_videos = []
    start = now - timedelta(days=days)
    for i, (name, language, base) in enumerate(NEWS + BUSINESS):
        ch = by_name[name]
        v = Video(youtube_video_id=f"demo-live-{i:02d}", channel_id=ch.id, title=TITLES[i % len(TITLES)], topic="Politics", live_started_at=start - timedelta(days=30))
        session.add(v)
        live_videos.append((ch, v, base))
    session.flush()
    for ch, v, base in live_videos:
        t = start
        while t <= now:
            hour = ((t + IST).hour + (t + IST).minute / 60)
            weekday_boost = 1.12 if (t + IST).weekday() >= 5 else 1.0
            level = base * _evening_curve(hour) * weekday_boost * (0.93 + 0.14 * rnd.random())
            if ch.name == FLAT:
                level = base * 0.9   # a flat line, not a wobble
            rows.append({"video_id": v.id, "channel_id": ch.id, "observed_at": t, "view_count": 1, "concurrent_viewers": int(level), "is_live": True, "classification": "LIVE", "source": "demo"})
            t += timedelta(minutes=2)
    for i in range(0, len(rows), 5000):
        session.execute(insert(Observation), rows[i:i + 5000])
    session.flush()

    # ---- uploads and audiences: news channels have a few videos and Shorts, creators publish regularly
    obs: list[dict] = []
    for i, (name, language, base) in enumerate(NEWS + BUSINESS):
        ch = by_name[name]
        for k in range(8):
            published = now - timedelta(days=k % 7, hours=3 + k)
            v = Video(youtube_video_id=f"demo-v{i:02d}-{k}", channel_id=ch.id, title=f"{TITLES[(i + k) % len(TITLES)]} ({k + 1})", topic=TOPICS[(i + k) % len(TOPICS)], published_at=published.strftime("%Y-%m-%dT%H:%M:%SZ"))
            session.add(v)
            session.flush()
            views = int(base * rnd.uniform(4, 12) * (1 + k / 8))
            obs.append({"video_id": v.id, "channel_id": ch.id, "observed_at": now - timedelta(minutes=20), "view_count": views, "like_count": int(views * rnd.uniform(0.01, 0.03)), "comment_count": int(views * 0.002),
                        "is_live": False, "classification": "SHORT" if k % 3 == 0 else "REGULAR_VIDEO", "source": "demo"})
        session.add(ChannelStats(channel_id=ch.id, observed_at=now - timedelta(days=8), subscribers=int(base * 60), total_views=1))
        session.add(ChannelStats(channel_id=ch.id, observed_at=now - timedelta(hours=1), subscribers=int(base * 60 * rnd.uniform(1.004, 1.02)), total_views=1))
    for i, (name, segment, subs) in enumerate(CREATORS):
        ch = by_name[name]
        session.add(ChannelStats(channel_id=ch.id, observed_at=now - timedelta(days=8), subscribers=subs, total_views=1))
        session.add(ChannelStats(channel_id=ch.id, observed_at=now - timedelta(hours=1), subscribers=int(subs * (1.01 + 0.012 * (5 - i) / 5)), total_views=1))
        for k in range(14):
            published = now - timedelta(days=k * 2 + 2, hours=i)
            v = Video(youtube_video_id=f"demo-c{i}-{k}", channel_id=ch.id, title=f"{name}: upload {k + 1}", topic=TOPICS[(i + k) % len(TOPICS)], published_at=published.strftime("%Y-%m-%dT%H:%M:%SZ"))
            session.add(v)
            session.flush()
            views = int(subs * rnd.uniform(0.04, 0.22) * (1.5 if (i == 1 and k % 4 == 0) else 1.0))
            cls = "SHORT" if k % 3 == 0 else "REGULAR_VIDEO"
            obs.append({"video_id": v.id, "channel_id": ch.id, "observed_at": now - timedelta(hours=1), "view_count": views, "like_count": int(views * (0.02 + 0.008 * i)), "comment_count": int(views * (0.002 + 0.001 * (4 - i % 4))),
                        "is_live": False, "classification": cls, "source": "demo"})
            if k >= 5:
                obs.append({"video_id": v.id, "channel_id": ch.id, "observed_at": now - timedelta(days=5), "view_count": int(views * 0.82), "like_count": 1, "comment_count": 0, "is_live": False, "classification": cls, "source": "demo"})
    session.execute(insert(Observation), obs)
    session.commit()

    today = (now + IST).date().isoformat()
    for name, ages, states in (("Sample News A", {"13-17": 4, "18-24": 18, "25-34": 34, "35-44": 26, "45-54": 12, "55-64": 5, "65+": 1}, {"Uttar Pradesh": 22, "Bihar": 14, "Madhya Pradesh": 9, "Delhi": 8, "Rajasthan": 7}),
                               ("Sample News B", {"13-17": 3, "18-24": 14, "25-34": 30, "35-44": 28, "45-54": 15, "55-64": 8, "65+": 2}, {"Uttar Pradesh": 19, "Bihar": 12, "Jharkhand": 7, "Maharashtra": 6}),
                               ("Sample Creator A", {"13-17": 8, "18-24": 34, "25-34": 33, "35-44": 15, "45-54": 7, "55-64": 3, "65+": 0}, {"Maharashtra": 15, "Karnataka": 12, "Delhi": 11, "Uttar Pradesh": 10})):
        audience.set_profile(session, channel_id=by_name[name].id, source="channel_media_kit", source_note="INVENTED sample profile for the demo; it is not a real audience", as_of=today, age=ages,
                             gender={"male": 66, "female": 34}, states=states, countries={"India": 96, "United States": 2, "United Arab Emirates": 2}, by="demo")
    _seed_social(session, channels, now, rnd)
    return {"channels": len(channels), "live_samples": len(rows), "uploads": len(obs)}


def _seed_social(session: Session, channels: list[Channel], now: datetime, rnd: random.Random) -> None:
    """Invented Facebook, Instagram and X accounts for the sample channels: handles that say sample, no address, a week of daily follower readings and a few posts each."""
    for i, ch in enumerate(channels[:12]):
        base = rnd.uniform(40_000, 900_000)
        for platform, share in (("instagram", 1.0), ("facebook", 1.6), ("x", 0.7)):
            if platform == "x" and i % 3 == 2:
                continue    # not every channel is on every platform
            acc = SocialAccount(channel_id=ch.id, platform=platform, handle=f"sample_{platform}_{i:02d}", display_name=f"{ch.name} (invented sample account)", active=True, last_status="ok", last_checked_at=now, last_ok_at=now)
            session.add(acc)
            session.flush()
            followers = base * share
            growth = rnd.uniform(0.0004, 0.004)
            for d in range(8, -1, -1):
                session.add(SocialStats(account_id=acc.id, observed_at=now - timedelta(days=d, hours=1), followers=int(followers * (1 + growth) ** (8 - d)), following=rnd.randint(20, 400), posts_total=3000 + (8 - d) * 3, source="demo"))
            for k in range(8):
                post = SocialPost(account_id=acc.id, platform_post_id=f"demo-{platform}-{i}-{k}", posted_at=now - timedelta(days=k * 0.9, hours=2 + k), text=f"Invented sample post {k + 1} of {ch.name}", media_type="post", api_refreshed_at=now)
                session.add(post)
                session.flush()
                reach = followers * rnd.uniform(0.002, 0.02) * (2.5 if k == 2 else 1.0)
                session.add(SocialPostStats(post_id=post.id, observed_at=now - timedelta(minutes=30), likes=int(reach), comments=int(reach * rnd.uniform(0.03, 0.1)), shares=int(reach * rnd.uniform(0.01, 0.06)) if platform != "instagram" else None,
                                            views=int(reach * rnd.uniform(8, 30)) if platform == "x" else None, source="demo"))
    session.commit()
