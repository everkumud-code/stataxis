"""A login's own channels: how a person is mapped to the channels that are theirs.

  * A person asks for a channel (picked from the tracked ones, or by pasting its @handle or link).
  * They are given a short code to put in the channel's own description. When StatAxis finds it there (one YouTube call), the channel is theirs: only someone who
    controls a channel can edit its description. They may delete the code afterwards.
  * An administrator can approve or reject any claim, and can map a channel to a login directly.
  * A channel that was not tracked yet is stored switched off. Tracking uses YouTube quota, so an administrator switches it on.

Nothing here reads anything private. The proof is a public description.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from collector.storage import Channel, User, UserChannel

CODE_PREFIX = "stataxis-"
_HANDLE_RE = re.compile(r"^@?([A-Za-z0-9._\-]{3,60})$")
_ID_RE = re.compile(r"^UC[A-Za-z0-9_\-]{22}$")
MAX_CLAIMS = int(os.getenv("STAXIS_MAX_CHANNEL_CLAIMS", "10"))
STATUSES = ("pending", "approved", "rejected")


def code_for(user_id: int, channel_id: int) -> str:
    """A code that belongs to this person and this channel, and cannot be guessed by anyone without the server's secret."""
    from api.auth import _secret

    digest = hmac.new(_secret(), f"channel-claim:{user_id}:{channel_id}".encode(), hashlib.sha256).hexdigest()
    return f"{CODE_PREFIX}{digest[:10]}"


def normalize_ref(text: str) -> str:
    """An @handle, a youtube.com/@handle link, a /channel/UC... link or a bare channel ID, as a URL. Name searches and /c/ links are refused: they cost far more quota."""
    raw = (text or "").strip()
    if not raw or len(raw) > 200:
        raise ValueError("paste the channel's @handle or its YouTube link")
    if "://" not in raw and (raw.lower().startswith(("youtube.com", "www.youtube.com", "m.youtube.com"))):
        raw = "https://" + raw
    if raw.lower().startswith("http"):
        from urllib.parse import unquote, urlparse

        parsed = urlparse(raw)
        if parsed.netloc.lower().split(":")[0] not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            raise ValueError("that is not a YouTube link")
        parts = [unquote(p) for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "channel" and _ID_RE.match(parts[1]):
            return f"https://www.youtube.com/channel/{parts[1]}"
        if parts and parts[0].startswith("@") and _HANDLE_RE.match(parts[0]):
            return f"https://www.youtube.com/{parts[0]}"
        raise ValueError("use the channel's @handle link (youtube.com/@name) or its /channel/ link")
    if _ID_RE.match(raw):
        return f"https://www.youtube.com/channel/{raw}"
    m = _HANDLE_RE.match(raw)
    if m:
        return f"https://www.youtube.com/@{m.group(1)}"
    raise ValueError("paste the channel's @handle or its YouTube link")


def _channel_payload(ch: Channel) -> dict[str, Any]:
    return {"id": ch.id, "name": ch.name, "segment": ch.segment or "news", "language": ch.language, "handle": ch.handle, "tracked": bool(ch.active), "youtube_channel_id": ch.youtube_channel_id}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def claim_payload(claim: UserChannel, channel: Channel, user: User | None = None) -> dict[str, Any]:
    out = {"id": claim.id, "status": claim.status, "method": claim.method, "code": claim.code if claim.status == "pending" else None, "note": claim.note, "decided_by": claim.decided_by,
           "requested_at": _iso(claim.requested_at), "decided_at": _iso(claim.decided_at), "channel": _channel_payload(channel)}
    if user is not None:
        out["user"] = {"id": user.id, "login": user.email, "name": user.full_name, "organization": user.organization}
    return out


def mine(session: Session, user_id: int) -> list[dict[str, Any]]:
    rows = (session.query(UserChannel, Channel).join(Channel, Channel.id == UserChannel.channel_id).filter(UserChannel.user_id == user_id).order_by(UserChannel.requested_at).all())
    return [claim_payload(c, ch) for c, ch in rows]


def approved_channel_ids(session: Session, user_id: int) -> list[int]:
    return [cid for (cid,) in session.query(UserChannel.channel_id).filter_by(user_id=user_id, status="approved").order_by(UserChannel.channel_id).all()]


def search_tracked(session: Session, user_id: int, q: str, limit: int = 15) -> list[dict[str, Any]]:
    text = (q or "").strip().lower()
    if len(text) < 2:
        return []
    like = f"%{text}%"
    taken = {cid for (cid,) in session.query(UserChannel.channel_id).filter_by(user_id=user_id).all()}
    rows = session.query(Channel).filter(Channel.active.is_(True), or_(func.lower(Channel.name).like(like), func.lower(func.coalesce(Channel.handle, "")).like(like))).order_by(Channel.name).limit(limit + len(taken)).all()
    return [_channel_payload(ch) for ch in rows if ch.id not in taken][:limit]


def _claim(session: Session, user: User, channel: Channel) -> UserChannel:
    existing = session.query(UserChannel).filter_by(user_id=user.id, channel_id=channel.id).one_or_none()
    if existing is not None:
        if existing.status == "rejected":
            existing.status, existing.method, existing.decided_at, existing.decided_by, existing.note = "pending", None, None, None, None
            session.commit()
        return existing
    held = session.query(func.count(UserChannel.id)).filter(UserChannel.user_id == user.id, UserChannel.status != "rejected").scalar() or 0
    if held >= MAX_CLAIMS:
        raise ValueError(f"you can map up to {MAX_CLAIMS} channels; remove one first or ask an administrator")
    claim = UserChannel(user_id=user.id, channel_id=channel.id, status="pending", code=code_for(user.id, channel.id))
    session.add(claim)
    session.commit()
    return claim


def claim_tracked(session: Session, user: User, channel_id: int) -> dict[str, Any]:
    channel = session.get(Channel, int(channel_id))
    if channel is None:
        raise LookupError("channel not found")
    return claim_payload(_claim(session, user, channel), channel)


def claim_by_ref(session: Session, user: User, ref: str, *, client: Any = None) -> dict[str, Any]:
    """Resolve a pasted handle or link (1 YouTube quota unit) and claim it. A channel StatAxis did not know is stored switched off."""
    url = normalize_ref(ref)
    owns = client is None
    if owns:
        from collector.youtube.client import YouTubeClient

        client = YouTubeClient()
    try:
        meta = client.resolve_channel_url(url)
    finally:
        if owns:
            client.close()
    youtube_id = str(meta.get("id") or "").strip()
    if not youtube_id:
        raise ValueError("YouTube did not return that channel")
    title = str((meta.get("snippet") or {}).get("title") or "").strip() or url
    channel = session.query(Channel).filter_by(youtube_channel_id=youtube_id).one_or_none()
    if channel is None:
        handle = url.rsplit("/", 1)[-1] if "/@" in url else None
        channel = Channel(youtube_channel_id=youtube_id, name=title[:255], network="Self-registered", language="unknown", region="unknown", active=False, segment="creator", handle=handle)
        session.add(channel)
        session.flush()
    return claim_payload(_claim(session, user, channel), channel)


def verify(session: Session, user: User, claim_id: int, *, client: Any = None) -> dict[str, Any]:
    """Look for the person's code in the channel's own description (1 YouTube quota unit). Found means the channel is theirs."""
    claim = session.get(UserChannel, int(claim_id))
    if claim is None or claim.user_id != user.id:
        raise LookupError("claim not found")
    channel = session.get(Channel, claim.channel_id)
    if claim.status == "approved":
        return {**claim_payload(claim, channel), "found": True}
    if claim.status == "rejected":
        raise PermissionError("an administrator declined this claim; ask them, or claim it again")
    owns = client is None
    if owns:
        from collector.youtube.client import YouTubeClient

        client = YouTubeClient()
    try:
        meta = client.get_channel(channel.youtube_channel_id)
    finally:
        if owns:
            client.close()
    description = str((meta.get("snippet") or {}).get("description") or "")
    found = claim.code.lower() in description.lower()
    if found:
        claim.status, claim.method, claim.decided_at, claim.decided_by = "approved", "code", datetime.now(UTC), "code found in the channel description"
        session.commit()
    return {**claim_payload(claim, channel), "found": found}


def remove(session: Session, user: User, claim_id: int) -> dict[str, Any]:
    claim = session.get(UserChannel, int(claim_id))
    if claim is None or claim.user_id != user.id:
        raise LookupError("claim not found")
    session.delete(claim)
    session.commit()
    return {"removed": True}


# ---------------------------------------------------------------- administrator
def list_claims(session: Session, status: str | None = None) -> list[dict[str, Any]]:
    q = session.query(UserChannel, Channel, User).join(Channel, Channel.id == UserChannel.channel_id).join(User, User.id == UserChannel.user_id)
    if status:
        if status not in STATUSES:
            raise ValueError("status must be pending, approved or rejected")
        q = q.filter(UserChannel.status == status)
    return [claim_payload(c, ch, u) for c, ch, u in q.order_by(UserChannel.status.desc(), UserChannel.requested_at.desc()).limit(500).all()]


def decide(session: Session, claim_id: int, decision: str, *, by: str, note: str = "", track: bool = False) -> dict[str, Any]:
    if decision not in {"approve", "reject"}:
        raise ValueError("decision must be approve or reject")
    claim = session.get(UserChannel, int(claim_id))
    if claim is None:
        raise LookupError("claim not found")
    channel = session.get(Channel, claim.channel_id)
    claim.status = "approved" if decision == "approve" else "rejected"
    claim.method = "admin" if decision == "approve" else claim.method
    claim.decided_by, claim.decided_at, claim.note = by, datetime.now(UTC), (note or "").strip()[:500] or None
    if decision == "approve" and track:
        channel.active = True
    session.commit()
    return claim_payload(claim, channel, session.get(User, claim.user_id))


def assign(session: Session, user_id: int, channel_id: int, *, by: str, track: bool = False) -> dict[str, Any]:
    """An administrator maps a channel to a login directly."""
    user, channel = session.get(User, int(user_id)), session.get(Channel, int(channel_id))
    if user is None or channel is None:
        raise LookupError("login or channel not found")
    claim = session.query(UserChannel).filter_by(user_id=user.id, channel_id=channel.id).one_or_none()
    if claim is None:
        claim = UserChannel(user_id=user.id, channel_id=channel.id, code=code_for(user.id, channel.id))
        session.add(claim)
    claim.status, claim.method, claim.decided_by, claim.decided_at, claim.note = "approved", "admin", by, datetime.now(UTC), None
    if track:
        channel.active = True
    session.commit()
    return claim_payload(claim, channel, user)


def admin_remove(session: Session, claim_id: int) -> dict[str, Any]:
    claim = session.get(UserChannel, int(claim_id))
    if claim is None:
        raise LookupError("claim not found")
    session.delete(claim)
    session.commit()
    return {"removed": True}
