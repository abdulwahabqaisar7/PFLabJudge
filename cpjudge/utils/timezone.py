"""Timezone handling for CPJudge with Pakistan Standard Time (PKT, UTC+5) support."""
from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    PKT_TZ = ZoneInfo("Asia/Karachi")
except Exception:
    PKT_TZ = timezone(timedelta(hours=5), name="PKT")


def now_pkt() -> datetime:
    """Returns the current datetime in Pakistan Standard Time (PKT)."""
    return datetime.now(PKT_TZ)


def to_pkt(dt: Optional[datetime]) -> Optional[datetime]:
    """Converts or localizes a datetime to Pakistan Standard Time (PKT).
    
    - If dt is None, returns None.
    - If dt is naive, assumes it represents PKT (local wall clock time) and attaches PKT tzinfo.
    - If dt is aware (e.g. UTC), converts it to PKT via astimezone.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=PKT_TZ)
    return dt.astimezone(PKT_TZ)


def ensure_pkt(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensures a datetime is timezone-aware in Pakistan Standard Time (PKT)."""
    return to_pkt(dt)


def format_pkt(dt: Optional[datetime], fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Formats a datetime in Pakistan Standard Time (PKT). Returns empty string if None."""
    if dt is None:
        return ""
    return to_pkt(dt).strftime(fmt)


# Backward-compatible aliases
utc_now = now_pkt
ensure_utc = to_pkt
