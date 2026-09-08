"""Shanghai session clock: day K is complete after 16:30."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
SESSION_CLOSE_HOUR = 16
SESSION_CLOSE_MINUTE = 30


def shanghai_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(SHANGHAI)
    if now.tzinfo is None:
        return now.replace(tzinfo=SHANGHAI)
    return now.astimezone(SHANGHAI)


def session_closed(now: datetime | None = None) -> bool:
    current = shanghai_now(now)
    close = current.replace(
        hour=SESSION_CLOSE_HOUR,
        minute=SESSION_CLOSE_MINUTE,
        second=0,
        microsecond=0,
    )
    return current >= close


def session_asof_date(now: datetime | None = None) -> str:
    """Latest calendar date whose regular session is already closed."""
    current = shanghai_now(now)
    day = current.date()
    if not session_closed(current):
        day = day - timedelta(days=1)
    return day.isoformat()
