"""Sending e-mail through Resend (https://resend.com): the one place where StatAxis talks to a mail service.

The API key and the From address are kept by an administrator in the workspace (Email delivery) and are never shown again in full; the environment (STAXIS_RESEND_API_KEY, STAXIS_MAIL_FROM)
overrides them. Without a key nothing is sent and the caller is told so: a report is then recorded as 'waiting for a mail key', not lost.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from collector.storage import AppSetting

API_URL = "https://api.resend.com/emails"
KEY_SETTING, FROM_SETTING, BASE_SETTING = "mail.resend_api_key", "mail.from", "mail.base_url"
DEFAULT_FROM = "StatAxis <reports@stataxis.org>"
DEFAULT_BASE = "https://www.stataxis.org"


class MailError(RuntimeError):
    """The mail service refused or could not be reached; the message is safe to show (it never contains the key)."""


def _get(session: Session, key: str) -> str:
    row = session.get(AppSetting, key)
    return (row.value or "").strip() if row else ""


def settings(session: Session) -> dict[str, str]:
    key = os.getenv("STAXIS_RESEND_API_KEY", "").strip() or _get(session, KEY_SETTING)
    return {"key": key, "from": os.getenv("STAXIS_MAIL_FROM", "").strip() or _get(session, FROM_SETTING) or DEFAULT_FROM, "base_url": (_get(session, BASE_SETTING) or DEFAULT_BASE).rstrip("/")}


def public_status(session: Session) -> dict[str, Any]:
    s = settings(session)
    return {"configured": bool(s["key"]), "key_hint": ("…" + s["key"][-4:]) if s["key"] else None, "from": s["from"], "base_url": s["base_url"], "source": "environment" if os.getenv("STAXIS_RESEND_API_KEY", "").strip() else "workspace"}


def save_settings(session: Session, by: str, *, key: str | None = None, sender: str | None = None, base_url: str | None = None) -> None:
    for name, value in ((KEY_SETTING, key), (FROM_SETTING, sender), (BASE_SETTING, base_url)):
        if value is None:
            continue
        value = value.strip()
        if name == KEY_SETTING and value and not value.startswith("re_"):
            raise ValueError("a Resend API key starts with re_")
        if name == FROM_SETTING and value and "@" not in value:
            raise ValueError("the From address must be an e-mail address, such as StatAxis <reports@stataxis.org>")
        if name == BASE_SETTING and value and not value.startswith("https://"):
            raise ValueError("the site address must start with https://")
        row = session.get(AppSetting, name)
        if row is None:
            row = AppSetting(key=name)
            session.add(row)
        row.value, row.updated_by, row.updated_at = value, by, datetime.now(UTC)
    session.commit()


def _post(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "StatAxis/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as res:  # noqa: S310 - a fixed https address
            return json.loads(res.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("message") or ""
        except (ValueError, OSError):
            detail = ""
        raise MailError(f"the mail service answered {exc.code}" + (f": {detail[:200]}" if detail else "")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise MailError("the mail service could not be reached") from exc


def send_email(session: Session, *, to: str, subject: str, html: str, text: str, attachments: list[tuple[str, bytes]] | None = None, unsubscribe_url: str | None = None) -> str:
    """Send one e-mail; returns the message id. Raises MailError (no key, refused, unreachable)."""
    cfg = settings(session)
    if not cfg["key"]:
        raise MailError("no mail key is set: an administrator has to add the Resend API key under Email delivery")
    payload: dict[str, Any] = {"from": cfg["from"], "to": [to], "subject": subject, "html": html, "text": text}
    if attachments:
        payload["attachments"] = [{"filename": name, "content": base64.b64encode(data).decode("ascii")} for name, data in attachments]
    if unsubscribe_url:
        payload["headers"] = {"List-Unsubscribe": f"<{unsubscribe_url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    return str(_post(cfg["key"], payload).get("id") or "")
