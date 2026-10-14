"""Small helpers shared by the weekly report, prime-time, creator score, media planner and authenticity radar."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta, timezone
from statistics import median
from typing import Any

from sqlalchemy import and_, event, func, select
from sqlalchemy.orm import Session

from api.live_monitor import language_group
from collector.storage import Channel, Observation, Video, effective_channel_language
from metrics.markets import normalize_segment

IST = timezone(timedelta(hours=5, minutes=30))
MAX_RANGE_DAYS = 31
_CHUNK = 400


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def now_utc() -> datetime:
    return datetime.now(UTC)


def parse_day(value: Any, field: str = "date") -> date:
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError as exc:
        raise ValueError(f"{field} must look like 2026-10-09") from exc


def ist_window(start_day: date, end_day: date) -> tuple[datetime, datetime]:
    """UTC start (inclusive) and end (exclusive) of the Indian days start_day .. end_day, both included."""
    if end_day < start_day:
        raise ValueError("the end date cannot be before the start date")
    if (end_day - start_day).days + 1 > MAX_RANGE_DAYS:
        raise ValueError(f"choose at most {MAX_RANGE_DAYS} days")
    start = datetime(start_day.year, start_day.month, start_day.day, tzinfo=IST).astimezone(UTC)
    end = (datetime(end_day.year, end_day.month, end_day.day, tzinfo=IST) + timedelta(days=1)).astimezone(UTC)
    return start, end


def ist_hours(day: date, start_hour: int, end_hour: int) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=IST) + timedelta(hours=start_hour)
    end = datetime(day.year, day.month, day.day, tzinfo=IST) + timedelta(hours=end_hour)
    return start.astimezone(UTC), end.astimezone(UTC)


def ist_minutes(day: date, start_minute: int, end_minute: int) -> tuple[datetime, datetime]:
    """UTC start and end of ``start_minute`` .. ``end_minute`` (minutes after midnight, Indian time; 1440 is the end of the day) on an Indian day."""
    midnight = datetime(day.year, day.month, day.day, tzinfo=IST)
    return (midnight + timedelta(minutes=start_minute)).astimezone(UTC), (midnight + timedelta(minutes=end_minute)).astimezone(UTC)


def parse_clock(value: Any, field: str) -> int:
    """'09:30' -> 570 minutes after midnight; '24:00' (the end of the day) -> 1440."""
    text = str(value or "").strip()
    try:
        hours, minutes = text.split(":")[:2] if ":" in text else (text, "0")
        h, m = int(hours), int(minutes)
    except ValueError as exc:
        raise ValueError(f"{field} must look like 09:30") from exc
    if not (0 <= m < 60 and 0 <= h <= 24 and (h < 24 or m == 0)):
        raise ValueError(f"{field} must be a time between 00:00 and 24:00")
    return h * 60 + m


def clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def today_ist(now: datetime | None = None) -> date:
    return (now or now_utc()).astimezone(IST).date()


def parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return utc(datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def pick_channels(session: Session, *, segment: str | None, language: str | None, channel_ids: list[int] | None = None) -> tuple[list[Channel], dict[int, str]]:
    """Active channels, optionally of one segment (news, business, print, party ...), one language or language group, and only the channels asked for."""
    segment_key = normalize_segment(segment) if segment else None
    target = language.strip().lower() if language and language.strip() else None
    channels, languages = [], {}
    wanted = set(channel_ids) if channel_ids else None
    for channel in session.query(Channel).filter(Channel.active.is_(True)).order_by(Channel.id).all():
        if wanted is not None and channel.id not in wanted:
            continue
        if segment_key and (channel.segment or "news") != segment_key:
            continue
        lang = effective_channel_language(session, channel)
        if target and language_group(lang).lower() != target and lang.lower() != target:
            continue
        channels.append(channel)
        languages[channel.id] = lang
    return channels, languages


def _latest_from_history(session: Session, chunk: list[int]) -> dict[int, Any]:
    """The newest observation of each video, found the portable way: the newest time per video, then the row at that time."""
    newest = select(Observation.video_id, func.max(Observation.observed_at).label("m")).where(Observation.video_id.in_(chunk)).group_by(Observation.video_id).subquery()
    stmt = select(*Observation.__table__.c).join(newest, and_(Observation.video_id == newest.c.video_id, Observation.observed_at == newest.c.m))
    return {row.video_id: row for row in session.execute(stmt)}


def _latest_by_probe(session: Session, chunk: list[int]) -> dict[int, Any]:
    """PostgreSQL: one look at the end of the (video, time) index for each video. The portable form reads the whole observations table once per chunk (about 100 ms each for half a million rows,
    and a briefing asks for tens of thousands of videos); this reads only the last row of each video."""
    from sqlalchemy import Integer, bindparam, cast, true
    from sqlalchemy.dialects.postgresql import ARRAY

    ids = select(func.unnest(cast(bindparam("ids", chunk, type_=ARRAY(Integer)), ARRAY(Integer))).label("id")).subquery()
    last = select(*Observation.__table__.c).where(Observation.video_id == ids.c.id).order_by(Observation.observed_at.desc()).limit(1).lateral()
    return {row.video_id: row for row in session.execute(select(*last.c).select_from(ids.join(last, true())))}


@event.listens_for(Session, "after_flush")
@event.listens_for(Session, "after_rollback")
def _forget_latest(session: Session, *_args: Any) -> None:
    """Anything written (or undone) in this session makes what was looked up stale."""
    session.info.pop("_latest_observations", None)
    session.info.pop("_channel_videos", None)


def channel_videos(session: Session, channel_ids: list[int]) -> list[Video]:
    """Every video of these channels, loaded once per request however many tools ask (a briefing asks four times; each load builds an object for each of tens of thousands of videos)."""
    memo: dict[int, list[Video]] = session.info.setdefault("_channel_videos", {})
    missing = [c for c in dict.fromkeys(channel_ids) if c not in memo]
    if missing:
        for c in missing:
            memo[c] = []
        for video in session.query(Video).filter(Video.channel_id.in_(missing)).order_by(Video.id).all():
            memo[video.channel_id].append(video)
    return [video for c in dict.fromkeys(channel_ids) for video in memo[c]]


def latest_observations(session: Session, video_ids: list[int]) -> dict[int, Any]:
    """The newest observation of each video, as a light read-only row (view_count, like_count, classification ... by name). Within one request (one session) a video is looked up once, however many tools ask for it."""
    memo: dict[int, Any] = session.info.setdefault("_latest_observations", {})
    missing = [v for v in dict.fromkeys(video_ids) if v not in memo]
    probe = bool(missing) and session.get_bind().dialect.name == "postgresql"
    size = 5000 if probe else _CHUNK
    for i in range(0, len(missing), size):
        chunk = missing[i:i + size]
        found = (_latest_by_probe if probe else _latest_from_history)(session, chunk)
        for v in chunk:
            memo[v] = found.get(v)
    return {v: memo[v] for v in video_ids if memo.get(v) is not None}


def mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def stdev(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return None
    m = sum(values) / len(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def robust_z(value: float, peers: list[float]) -> float | None:
    """How far a value sits from its peers, in robust (median / MAD) units. None when there are too few peers or no spread."""
    peers = [p for p in peers if p is not None]
    if len(peers) < 4:
        return None
    centre = median(peers)
    mad = median([abs(p - centre) for p in peers]) * 1.4826
    if mad <= 0:
        return None
    return (value - centre) / mad


def percentile_rank(value: float, peers: list[float]) -> float:
    """0..100: the share of peers this value beats (ties count half)."""
    peers = [p for p in peers if p is not None]
    if not peers:
        return 0.0
    below = sum(1 for p in peers if p < value)
    equal = sum(1 for p in peers if p == value)
    return 100.0 * (below + 0.5 * equal) / len(peers)


def rnd(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)
