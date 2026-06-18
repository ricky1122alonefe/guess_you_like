"""Beijing time (UTC+8 / Asia/Shanghai) helpers for display and logging."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    BEIJING = ZoneInfo("Asia/Shanghai")
except ImportError:
    BEIJING = timezone(timedelta(hours=8))

_FMTS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S.%f%z",
)


def now_beijing() -> datetime:
    return datetime.now(BEIJING)


def now_beijing_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return now_beijing().strftime(fmt)


def to_beijing(dt: datetime) -> datetime:
    """Convert aware/naive datetime to Asia/Shanghai."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=BEIJING)
    return dt.astimezone(BEIJING)


def coerce_beijing_dt(value) -> datetime | None:
    """Parse str/datetime and always return timezone-aware Beijing time."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return to_beijing(value)
    dt = parse_ts(value)
    return to_beijing(dt) if dt else None


def format_beijing(dt: datetime | None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    if dt is None:
        return "—"
    return to_beijing(dt).strftime(fmt)


def _parse_ts_string(text: str) -> datetime | None:
    s = text.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    for fmt in _FMTS:
        try:
            n = len(fmt.replace("%z", "+0000").replace("%f", "000000"))
            return datetime.strptime(s[:n], fmt)
        except ValueError:
            continue
    if len(s) >= 19:
        try:
            return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return None


def parse_ts(value) -> datetime | None:
    """Parse common timestamp string (Beijing-naive or aware)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return _parse_ts_string(str(value))


def format_ts(value, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format timestamp for UI — DB UTC values are converted to Beijing."""
    if value is None or value == "":
        return "—"
    if isinstance(value, datetime):
        return format_beijing(value, fmt)
    if isinstance(value, str):
        raw = value.strip()
        dt = _parse_ts_string(raw)
        if dt is None:
            return raw
        if dt.tzinfo is not None:
            return format_beijing(dt, fmt)
        return dt.strftime(fmt)
    return str(value)


def chart_time_label(value) -> str:
    """Short HH:MM label for charts (Beijing)."""
    return format_ts(value, "%H:%M")


def beijing_date(value) -> str | None:
    """YYYY-MM-DD in Beijing for grouping."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return to_beijing(value).date().isoformat()
    if isinstance(value, str):
        dt = _parse_ts_string(value)
        if dt:
            if dt.tzinfo is not None:
                return to_beijing(dt).date().isoformat()
            return dt.date().isoformat()
        return value[:10] if len(value) >= 10 else None
    if isinstance(value, date):
        return value.isoformat()
    return None


def beijing_hour_key(value) -> str:
    """Hour bucket key YYYY-MM-DD HH (Beijing)."""
    if isinstance(value, datetime):
        return to_beijing(value).strftime("%Y-%m-%d %H")
    s = format_ts(value, "%Y-%m-%d %H:%M:%S")
    return s[:13] if len(s) >= 13 else s
