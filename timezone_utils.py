from datetime import datetime, timezone, timedelta

# Moscow timezone (UTC+3)
MOSCOW_TZ = timezone(timedelta(hours=3))


def now_moscow() -> datetime:
    """Return current datetime in Moscow timezone."""
    return datetime.now(MOSCOW_TZ)


def to_moscow(dt: datetime | None) -> datetime | None:
    """
    Convert a datetime to Moscow timezone.
    
    If the datetime is naive (no timezone info), it's assumed to be UTC.
    """
    if dt is None:
        return None
    
    if dt.tzinfo is None:
        # Assume naive datetime is UTC
        dt = dt.replace(tzinfo=timezone.utc)
    
    return dt.astimezone(MOSCOW_TZ)


def format_moscow(dt: datetime | None, fmt: str = "%d.%m %H:%M") -> str:
    """Format a datetime in Moscow timezone."""
    moscow_dt = to_moscow(dt)
    if moscow_dt is None:
        return "—"
    return moscow_dt.strftime(fmt)
