"""The time of a download, in Indian time. Every report, workbook, sheet and picture a person takes out of StatAxis prints it, and its file name carries it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def ist_stamp(moment: datetime | None = None) -> str:
    """A moment in Indian time as people write it, e.g. 12 Oct 2026, 3:42 PM IST."""
    t = (moment or datetime.now(UTC)).astimezone(IST)
    return f"{t.day} {t:%b %Y}, {t.hour % 12 or 12}:{t:%M} {'AM' if t.hour < 12 else 'PM'} IST"


def ist_cell(value):
    """A time for a spreadsheet cell, in Indian time without a zone (Excel cannot hold zones). A naive time from the database is UTC; text such as 2026-10-12T11:45:00+00:00 is read first."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(IST).replace(tzinfo=None)


def file_stamp(moment: datetime | None = None) -> str:
    """The same moment for a file name: 20261012-1542 (Indian time)."""
    return (moment or datetime.now(UTC)).astimezone(IST).strftime("%Y%m%d-%H%M")
