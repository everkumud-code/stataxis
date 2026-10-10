"""Small helpers shared by the weekly report, prime-time, creator score, media planner and authenticity radar."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta, timezone
from statistics import median
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from api.live_monitor import language_group
from collector.storage import Channel, Observation, effective_channel_language
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


def latest_observations(session: Session, video_ids: list[int]) -> dict[int, Observation]:
    """The newest observation of each video."""
    out: dict[int, Observation] = {}
    for i in range(0, len(video_ids), _CHUNK):
        chunk = video_ids[i:i + _CHUNK]
        newest = select(Observation.video_id, func.max(Observation.observed_at).label("m")).where(Observation.video_id.in_(chunk)).group_by(Observation.video_id).subquery()
        stmt = select(Observation).join(newest, and_(Observation.video_id == newest.c.video_id, Observation.observed_at == newest.c.m))
        for obs in session.execute(stmt).scalars():
            out[obs.video_id] = obs
    return out


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
