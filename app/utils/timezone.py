"""
Timezone utilities for Eastern Time handling.

All dates in the application should be displayed in Eastern Time,
automatically handling Daylight Saving Time transitions.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Eastern Time zone (handles DST automatically)
EASTERN_TZ = ZoneInfo("America/New_York")


def now_eastern() -> datetime:
    """Get current datetime in Eastern Time (with DST handling)."""
    return datetime.now(EASTERN_TZ)


def utc_to_eastern(dt: datetime) -> datetime:
    """
    Convert a UTC datetime to Eastern Time.

    Args:
        dt: A datetime object (naive assumed UTC, or timezone-aware)

    Returns:
        datetime in Eastern Time
    """
    if dt is None:
        return None

    # If naive, assume UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(EASTERN_TZ)


def eastern_to_utc(dt: datetime) -> datetime:
    """
    Convert an Eastern Time datetime to UTC.

    Args:
        dt: A datetime object in Eastern Time

    Returns:
        datetime in UTC
    """
    if dt is None:
        return None

    # If naive, assume Eastern
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=EASTERN_TZ)

    return dt.astimezone(timezone.utc)


def format_eastern(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S %Z") -> str:
    """
    Format a datetime as Eastern Time string.

    Args:
        dt: A datetime object (naive assumed UTC, or timezone-aware)
        fmt: strftime format string (default includes timezone abbreviation)

    Returns:
        Formatted string in Eastern Time
    """
    if dt is None:
        return None

    eastern_dt = utc_to_eastern(dt)
    return eastern_dt.strftime(fmt)


def format_eastern_iso(dt: datetime) -> str:
    """
    Format a datetime as ISO 8601 string in Eastern Time.

    Args:
        dt: A datetime object (naive assumed UTC, or timezone-aware)

    Returns:
        ISO 8601 formatted string in Eastern Time
    """
    if dt is None:
        return None

    eastern_dt = utc_to_eastern(dt)
    return eastern_dt.isoformat()


def get_eastern_date_str(dt: datetime = None) -> str:
    """
    Get date string in Eastern Time (YYYY-MM-DD format).

    Args:
        dt: Optional datetime (defaults to now)

    Returns:
        Date string in Eastern Time
    """
    if dt is None:
        dt = now_eastern()
    else:
        dt = utc_to_eastern(dt)

    return dt.strftime("%Y-%m-%d")


def get_eastern_datetime_str(dt: datetime = None) -> str:
    """
    Get datetime string in Eastern Time for display.

    Args:
        dt: Optional datetime (defaults to now)

    Returns:
        Formatted datetime string like "Dec 1, 2025 12:30 PM EST"
    """
    if dt is None:
        dt = now_eastern()
    else:
        dt = utc_to_eastern(dt)

    return dt.strftime("%b %d, %Y %I:%M %p %Z")


def is_dst() -> bool:
    """Check if Eastern Time is currently in Daylight Saving Time."""
    now = now_eastern()
    return now.dst() != timezone.utc.utcoffset(None)


def get_timezone_info() -> dict:
    """Get current timezone information."""
    now = now_eastern()
    return {
        "timezone": "America/New_York",
        "abbreviation": now.strftime("%Z"),  # EST or EDT
        "utc_offset": now.strftime("%z"),    # -0500 or -0400
        "is_dst": bool(now.dst()),
        "current_time": now.isoformat()
    }
