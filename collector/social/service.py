"""Reading the accounts, storing what was read, and taking figures from a sheet.

A pass (``collect_social``) reads each active account that is due, through the platform's connector, and stores one reading of the account (followers, accounts followed, number of posts) and the latest
posts with what each had gathered. An account is read again after the interval an administrator set (6 hours by default); X accounts are read at most as many times per pass as the administrator allows.
A platform without a key is not an error: its accounts stay as they are, marked "no key saved yet". Figures a sheet or an administrator supplies are stored the same way, marked as imported or typed in.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from collector.social import settings as social_settings
from collector.social.base import PLATFORM_LABEL, AccountSnapshot, Fetched, PostSnapshot, SocialError, clean_handle, clip, parse_time, to_int, valid_handle
from collector.social.connectors import connectors as build_connectors
from collector.storage import Channel, SocialAccount, SocialPost, SocialPostStats, SocialStats, SOCIAL_PLATFORMS

logger = logging.getLogger(__name__)
IST = timedelta(hours=5, minutes=30)
MAX_CSV_BYTES = 2_000_000
MAX_CSV_ROWS = 5000
MAX_COUNT = 5_000_000_000      # more than any account on earth: a bigger figure is a typing error


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC)


# ------------------------------------------------------------------------------------------------------------------------------ accounts
def find_channel(session: Session, ref: str) -> Channel | None:
    """A channel from what a sheet calls it: its StatAxis number, its YouTube channel id, its YouTube @handle, or its exact name."""
    value = (ref or "").strip()
    if not value:
        return None
    if value.isdigit():
        found = session.get(Channel, int(value))
        if found:
            return found
    found = session.query(Channel).filter(Channel.youtube_channel_id == value).first()
    if found:
        return found
    lowered = value.lstrip("@").lower()
    found = session.query(Channel).filter(func.lower(Channel.handle).in_([lowered, "@" + lowered])).first()
    if found:
        return found
    return session.query(Channel).filter(func.lower(Channel.name) == value.lower()).first()


def save_account(session: Session, *, channel_id: int, platform: str, handle: str, by: str, active: bool = True, account_id: int | None = None) -> SocialAccount:
    platform = (platform or "").strip().lower()
    if platform == "twitter":
        platform = "x"
    if platform not in SOCIAL_PLATFORMS:
        raise ValueError("the platform must be facebook, instagram or x")
    cleaned = clean_handle(handle, platform)
    if not cleaned or not valid_handle(cleaned, platform):
        raise ValueError(f"'{handle}' is not a valid {PLATFORM_LABEL[platform]} handle")
    if session.get(Channel, channel_id) is None:
        raise LookupError("that channel does not exist")
    twin = session.query(SocialAccount).filter(SocialAccount.platform == platform, func.lower(SocialAccount.handle) == cleaned.lower()).first()
    if account_id is not None:
        row = session.get(SocialAccount, account_id)
        if row is None:
            raise LookupError("that account does not exist")
        if twin and twin.id != row.id:
            raise ValueError(f"{PLATFORM_LABEL[platform]} account '{cleaned}' is already linked to another channel")
    else:
        row = twin
        if row is None:
            row = SocialAccount(channel_id=channel_id, platform=platform, handle=cleaned, added_by=by)
            session.add(row)
    changed = (row.handle, row.platform) != (cleaned, platform)
    row.channel_id, row.platform, row.handle, row.active = channel_id, platform, cleaned, bool(active)
    if changed:
        row.external_id = row.display_name = row.last_status = row.last_error = None
    session.commit()
    return row


def delete_account(session: Session, account_id: int) -> dict[str, int]:
    row = session.get(SocialAccount, account_id)
    if row is None:
        raise LookupError("that account does not exist")
    post_ids = [p for (p,) in session.query(SocialPost.id).filter(SocialPost.account_id == account_id)]
    for i in range(0, len(post_ids), 500):
        session.query(SocialPostStats).filter(SocialPostStats.post_id.in_(post_ids[i:i + 500])).delete(synchronize_session=False)
    session.query(SocialPost).filter(SocialPost.account_id == account_id).delete(synchronize_session=False)
    session.query(SocialStats).filter(SocialStats.account_id == account_id).delete(synchronize_session=False)
    session.delete(row)
    session.commit()
    return {"deleted_posts": len(post_ids)}


# ------------------------------------------------------------------------------------------------------------------------------ storing a reading
def store_reading(session: Session, account: SocialAccount, fetched: Fetched, now: datetime, source: str = "api") -> dict[str, int]:
    """Store one reading of an account and its latest posts. Returns how many posts were new."""
    snap = fetched.account
    if snap.external_id:
        account.external_id = snap.external_id
    if snap.display_name:
        account.display_name = snap.display_name[:255]
    if snap.url:
        account.url = snap.url[:500]
    exists = session.query(SocialStats.id).filter_by(account_id=account.id, observed_at=now).first()
    if not exists and any(v is not None for v in (snap.followers, snap.following, snap.posts_total)):
        session.add(SocialStats(account_id=account.id, observed_at=now, followers=snap.followers, following=snap.following, posts_total=snap.posts_total, source=source))
    new_posts = 0
    known = {p.platform_post_id: p for p in session.query(SocialPost).filter(SocialPost.account_id == account.id, SocialPost.platform_post_id.in_([p.post_id for p in fetched.posts] or [""]))}
    for p in fetched.posts:
        row = known.get(p.post_id)
        if row is None:
            row = SocialPost(account_id=account.id, platform_post_id=p.post_id[:64])
            session.add(row)
            session.flush()
            new_posts += 1
        row.posted_at = p.posted_at or row.posted_at
        row.text = clip(p.text) or row.text
        row.permalink = (p.permalink or row.permalink or None)
        row.media_type = (p.media_type or row.media_type or None)
        row.api_refreshed_at = now
        if any(v is not None for v in (p.likes, p.comments, p.shares, p.views)) and not session.query(SocialPostStats.id).filter_by(post_id=row.id, observed_at=now).first():
            session.add(SocialPostStats(post_id=row.id, observed_at=now, likes=p.likes, comments=p.comments, shares=p.shares, views=p.views, source=source))
    return {"new_posts": new_posts, "posts": len(fetched.posts)}


def _mark(account: SocialAccount, status: str, error: str | None, now: datetime, *, checked: bool = True) -> None:
    if checked:
        account.last_checked_at = now
    account.last_status, account.last_error = status, (error or None)
    if status == "ok":
        account.last_ok_at = now


def check_account(session: Session, account: SocialAccount, *, now: datetime | None = None, connector_map: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read one account now. Returns what happened; the account's status is updated either way."""
    now = _now(now)
    connector_map = connector_map or build_connectors(social_settings.credentials(session))
    connector = connector_map[account.platform]
    if not connector.ready():
        _mark(account, "not_configured", "no key is saved for this platform yet", now, checked=False)
        session.commit()
        return {"status": "not_configured", "message": account.last_error}
    try:
        fetched = connector.fetch(account.handle, account.external_id)
    except SocialError as exc:
        _mark(account, exc.code, str(exc), now)
        session.commit()
        return {"status": exc.code, "message": str(exc)}
    result = store_reading(session, account, fetched, now)
    _mark(account, "ok", None, now)
    session.commit()
    return {"status": "ok", "followers": fetched.account.followers, **result}


def collect_social(session: Session, *, now: datetime | None = None, connector_map: dict[str, Any] | None = None, force: bool = False, only_account: int | None = None, limit: int | None = None) -> dict[str, Any]:
    """Read every active account that is due. X is limited per pass (X charges for reads); a platform that says "too many requests" is left alone until the next pass."""
    now = _now(now)
    connector_map = connector_map or build_connectors(social_settings.credentials(session))
    interval = timedelta(hours=social_settings.interval_hours(session))
    x_left = social_settings.x_limit(session)
    counts = {"read": 0, "new_posts": 0, "no_key": 0, "failed": 0, "skipped_x_limit": 0, "rate_limited": [], "left_for_next_pass": 0}
    attempted = 0
    query = session.query(SocialAccount).filter(SocialAccount.active.is_(True))
    if only_account is not None:
        query = query.filter(SocialAccount.id == only_account)
    accounts = query.order_by(SocialAccount.last_checked_at.is_(None).desc(), SocialAccount.last_checked_at.asc(), SocialAccount.id.asc()).all()
    stopped: set[str] = set()
    for account in accounts:
        if account.platform in stopped:
            continue
        if not force and account.last_checked_at is not None and _aware(account.last_checked_at) > now - interval:
            continue
        connector = connector_map[account.platform]
        if not connector.ready():
            _mark(account, "not_configured", "no key is saved for this platform yet", now, checked=False)
            counts["no_key"] += 1
            continue
        if account.platform == "x":
            if x_left <= 0:
                counts["skipped_x_limit"] += 1
                continue
            x_left -= 1
        if limit is not None and attempted >= limit:
            counts["left_for_next_pass"] += 1      # a pass reads only so many accounts, so the jobs thread is never held for minutes; the rest come next time
            continue
        attempted += 1
        outcome = check_account(session, account, now=now, connector_map=connector_map)
        if outcome["status"] == "ok":
            counts["read"] += 1
            counts["new_posts"] += outcome.get("new_posts", 0)
        else:
            counts["failed"] += 1
            if outcome["status"] == "rate_limited":
                stopped.add(account.platform)
                counts["rate_limited"].append(account.platform)
            elif outcome["status"] == "auth":
                stopped.add(account.platform)      # a refused key is refused for every account of the platform: do not hammer it
        logger.info("social %s/%s -> %s", account.platform, account.handle, outcome["status"])
    session.commit()
    return counts


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# ------------------------------------------------------------------------------------------------------------------------------ sheets
def _rows(text: str) -> list[dict[str, str]]:
    if len(text.encode("utf-8")) > MAX_CSV_BYTES:
        raise ValueError("the sheet is larger than 2 MB")
    text = text.lstrip("﻿")
    sample = text[:2000]
    delimiter = ";" if sample.count(";") > sample.count(",") and sample.count(";") > sample.count("\t") else "\t" if sample.count("\t") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("the sheet is empty")
    reader.fieldnames = [str(h or "").strip().lower().replace(" ", "_") for h in reader.fieldnames]
    rows = []
    for row in reader:
        rows.append({k: (v or "").strip() for k, v in row.items() if k})
        if len(rows) > MAX_CSV_ROWS:
            raise ValueError(f"the sheet has more than {MAX_CSV_ROWS} rows; split it")
    return rows


def _first(row: dict[str, str], *names: str) -> str:
    for name in names:
        if row.get(name):
            return row[name]
    return ""


def _account_for(session: Session, platform: str, handle: str) -> SocialAccount | None:
    platform = "x" if platform.strip().lower() == "twitter" else platform.strip().lower()
    cleaned = clean_handle(handle, platform)
    return session.query(SocialAccount).filter(SocialAccount.platform == platform, func.lower(SocialAccount.handle) == cleaned.lower()).first()


def import_accounts(session: Session, text: str, by: str) -> dict[str, Any]:
    """Columns: channel (StatAxis number, YouTube channel id, YouTube @handle or exact name), platform, handle. Several platforms for one channel are several rows."""
    out: dict[str, Any] = {"added": 0, "updated": 0, "errors": []}
    for n, row in enumerate(_rows(text), start=2):
        channel = find_channel(session, _first(row, "channel", "channel_id", "youtube_handle", "youtube", "name"))
        platform, handle = _first(row, "platform", "network"), _first(row, "handle", "account", "username", "url", "link")
        if channel is None:
            out["errors"].append({"row": n, "error": f"channel '{_first(row, 'channel', 'channel_id', 'youtube_handle', 'youtube', 'name')}' was not found"})
            continue
        try:
            existing = _account_for(session, platform, handle)
            save_account(session, channel_id=channel.id, platform=platform, handle=handle, by=by, account_id=existing.id if existing else None)
            out["updated" if existing else "added"] += 1
        except (ValueError, LookupError) as exc:
            session.rollback()
            out["errors"].append({"row": n, "error": str(exc)})
    return out


def _number(raw: str, what: str) -> int | None:
    if raw == "":
        return None
    n = to_int(raw)
    if n is None or n > MAX_COUNT:
        raise ValueError(f"{what} '{raw}' is not a sensible whole number")
    return n


def _day_time(raw: str) -> datetime:
    """A date from a sheet (2026-10-12, 12/10/2026 or 12-10-2026) as noon Indian time that day."""
    value = raw.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            d = datetime.strptime(value[:10], fmt).date()
            break
        except ValueError:
            continue
    else:
        parsed = parse_time(value)
        if parsed is None:
            raise ValueError(f"the date '{raw}' is not a date (write it as 2026-10-12)")
        d = (parsed + IST).date()
    if d > (datetime.now(UTC) + IST).date():
        raise ValueError(f"the date {d.isoformat()} is in the future")
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=UTC) - IST


def import_stats(session: Session, text: str) -> dict[str, Any]:
    """Columns: platform, handle, date, followers, following (optional), posts (optional). The account must already be linked."""
    out: dict[str, Any] = {"stored": 0, "errors": []}
    for n, row in enumerate(_rows(text), start=2):
        try:
            account = _account_for(session, _first(row, "platform", "network"), _first(row, "handle", "account", "username"))
            if account is None:
                raise ValueError("this platform and handle are not linked to a channel yet (import or add the account first)")
            when = _day_time(_first(row, "date", "day", "as_of"))
            followers, following, posts = _number(_first(row, "followers", "fans", "likes"), "followers"), _number(_first(row, "following", "follows"), "following"), _number(_first(row, "posts", "posts_total", "media_count"), "posts")
            if followers is None and following is None and posts is None:
                raise ValueError("the row has no followers, following or posts figure")
            save_stats_row(session, account, when, followers, following, posts, "import")
            out["stored"] += 1
        except ValueError as exc:
            out["errors"].append({"row": n, "error": str(exc)})
    session.commit()
    return out


def save_stats_row(session: Session, account: SocialAccount, when: datetime, followers: int | None, following: int | None, posts: int | None, source: str) -> None:
    row = session.query(SocialStats).filter_by(account_id=account.id, observed_at=when).one_or_none()
    if row is None:
        row = SocialStats(account_id=account.id, observed_at=when)
        session.add(row)
    row.followers, row.following, row.posts_total, row.source = followers, following, posts, source


def import_posts(session: Session, text: str, now: datetime | None = None) -> dict[str, Any]:
    """Columns: platform, handle, post_id, posted_at, text, permalink, likes, comments, shares, views. The figures are stored as of now."""
    now, out = _now(now), {"posts": 0, "new_posts": 0, "errors": []}
    for n, row in enumerate(_rows(text), start=2):
        try:
            account = _account_for(session, _first(row, "platform", "network"), _first(row, "handle", "account", "username"))
            if account is None:
                raise ValueError("this platform and handle are not linked to a channel yet")
            post_id = _first(row, "post_id", "id")[:64]
            if not post_id:
                raise ValueError("the row has no post_id")
            posted = _first(row, "posted_at", "date", "time")
            when = parse_time(posted) if posted else None
            if posted and when is None:
                when = _day_time(posted)
            snap = PostSnapshot(post_id=post_id, posted_at=when, text=clip(_first(row, "text", "caption", "message")), permalink=_first(row, "permalink", "url", "link") or None, media_type=_first(row, "media_type", "type") or None,
                                likes=_number(row.get("likes", ""), "likes"), comments=_number(row.get("comments", ""), "comments"), shares=_number(row.get("shares", ""), "shares"), views=_number(row.get("views", ""), "views"))
            result = store_reading(session, account, Fetched(AccountSnapshot(), [snap]), now, source="import")
            out["posts"] += 1
            out["new_posts"] += result["new_posts"]
        except ValueError as exc:
            out["errors"].append({"row": n, "error": str(exc)})
    session.commit()
    return out


def add_manual_stats(session: Session, account_id: int, *, day: str, followers: Any, following: Any = None, posts: Any = None, by: str = "") -> dict[str, Any]:
    account = session.get(SocialAccount, account_id)
    if account is None:
        raise LookupError("that account does not exist")
    when = _day_time(str(day))
    f, g, p = _number(str(followers if followers is not None else ""), "followers"), _number(str(following if following is not None else ""), "following"), _number(str(posts if posts is not None else ""), "posts")
    if f is None and g is None and p is None:
        raise ValueError("give at least the followers figure")
    save_stats_row(session, account, when, f, g, p, "manual")
    session.commit()
    return {"stored": True, "date": (when + IST).date().isoformat()}


def day_of(value: datetime) -> date:
    return (_aware(value) + IST).date()
