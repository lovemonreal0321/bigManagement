"""Timezone and business-day helpers.

Rules of the road (spec §44):

* Everything persisted is UTC and timezone-aware in Python.
* A "local day" only means something relative to an explicit timezone, so every
  day-boundary helper takes a tz argument rather than guessing.
* `date` columns (applied_date, follow-up due_date) are genuinely date-only and
  are interpreted in the *display* timezone when converted to instants.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = UTC


def utcnow() -> datetime:
    """Current instant, timezone-aware, in UTC."""
    return datetime.now(UTC)


def get_tz(name: str | None) -> ZoneInfo:
    """Resolve a tz name, falling back to UTC if it is unknown/blank."""
    if not name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def is_valid_timezone(name: str | None) -> bool:
    if not name:
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def to_utc(value: datetime, assume_tz: str | None = None) -> datetime:
    """Normalise a datetime to aware UTC.

    A naive value is interpreted in `assume_tz` (default UTC) rather than the
    server's local timezone — server-local would be an invisible dependency on
    where the process happens to run.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=get_tz(assume_tz) if assume_tz else UTC)
    return value.astimezone(UTC)


def to_tz(value: datetime, tz_name: str | None) -> datetime:
    """Render an instant in a display timezone."""
    return to_utc(value).astimezone(get_tz(tz_name))


def local_date(value: datetime, tz_name: str | None) -> date:
    """The calendar date an instant falls on, in a given timezone."""
    return to_tz(value, tz_name).date()


def day_bounds(day: date, tz_name: str | None) -> tuple[datetime, datetime]:
    """[start, end) instants of a local calendar day, as UTC."""
    tz = get_tz(tz_name)
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def range_bounds(
    start_day: date, end_day: date, tz_name: str | None
) -> tuple[datetime, datetime]:
    """[start, end) instants spanning two inclusive local dates, as UTC."""
    start, _ = day_bounds(start_day, tz_name)
    _, end = day_bounds(end_day, tz_name)
    return start, end


def start_of_week(day: date, week_starts_on: int = 0) -> date:
    """Monday-based by default (0 = Monday ... 6 = Sunday)."""
    offset = (day.weekday() - week_starts_on) % 7
    return day - timedelta(days=offset)


def start_of_month(day: date) -> date:
    return day.replace(day=1)


def end_of_month(day: date) -> date:
    if day.month == 12:
        return day.replace(day=31)
    return day.replace(month=day.month + 1, day=1) - timedelta(days=1)


def add_business_days(start: date, days: int) -> date:
    """Add N business days (Mon-Fri), skipping weekends.

    `add_business_days(friday, 1)` is the following Monday. Public holidays are
    not modelled — they vary by country and the spec does not call for them.
    """
    if days == 0:
        return start
    step = 1 if days > 0 else -1
    remaining = abs(days)
    current = start
    while remaining > 0:
        current += timedelta(days=step)
        if current.weekday() < 5:  # Mon-Fri
            remaining -= 1
    return current


def business_days_between(start: date, end: date) -> int:
    """Count business days in [start, end). Negative if end precedes start."""
    if end == start:
        return 0
    sign = 1 if end > start else -1
    lo, hi = (start, end) if sign == 1 else (end, start)
    count = 0
    current = lo
    while current < hi:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count * sign


def overlaps(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> bool:
    """Half-open interval overlap: [a_start, a_end) vs [b_start, b_end).

    Back-to-back meetings (one ends exactly when the next begins) do NOT
    overlap — that is a normal schedule, not a conflict (spec §43).
    """
    return a_start < b_end and b_start < a_end


def humanize_duration_days(days: int) -> str:
    if days == 0:
        return "today"
    if days == 1:
        return "1 day"
    return f"{days} days"
