"""Analytics period resolution (spec §55)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.core.errors import ValidationError
from app.core.timeutils import end_of_month, start_of_month, start_of_week

PERIOD_LABELS: dict[str, str] = {
    "all_time": "All Time",
    "today": "Today",
    "this_week": "This Week",
    "last_7_days": "Last 7 Days",
    "last_30_days": "Last 30 Days",
    "this_month": "This Month",
    "last_month": "Last Month",
    "custom": "Custom Range",
}


@dataclass(frozen=True)
class Period:
    key: str
    label: str
    #: None on both ends means "all time" — no date filtering at all.
    start: date | None
    end: date | None

    def contains(self, day: date | None) -> bool:
        if day is None:
            return self.start is None and self.end is None
        if self.start is not None and day < self.start:
            return False
        return self.end is None or day <= self.end


def resolve_period(
    key: str,
    *,
    today: date,
    start: date | None = None,
    end: date | None = None,
    week_starts_on: int = 0,
) -> Period:
    """Turn a period key into concrete inclusive date bounds."""
    label = PERIOD_LABELS.get(key, PERIOD_LABELS["all_time"])

    match key:
        case "today":
            return Period(key, label, today, today)
        case "this_week":
            begin = start_of_week(today, week_starts_on)
            return Period(key, label, begin, begin + timedelta(days=6))
        case "last_7_days":
            return Period(key, label, today - timedelta(days=6), today)
        case "last_30_days":
            return Period(key, label, today - timedelta(days=29), today)
        case "this_month":
            return Period(key, label, start_of_month(today), end_of_month(today))
        case "last_month":
            last = start_of_month(today) - timedelta(days=1)
            return Period(key, label, start_of_month(last), end_of_month(last))
        case "custom":
            if start is None or end is None:
                raise ValidationError(
                    "A custom range needs both a start and an end date.",
                    code="missing_custom_range",
                )
            if end < start:
                raise ValidationError(
                    "The end date must be on or after the start date.",
                    code="invalid_range",
                )
            return Period(key, label, start, end)
        case _:
            return Period("all_time", PERIOD_LABELS["all_time"], None, None)


def previous_period(period: Period) -> Period | None:
    """The equally-long window immediately before this one, for deltas."""
    if period.start is None or period.end is None:
        return None
    span = (period.end - period.start).days + 1
    new_end = period.start - timedelta(days=1)
    return Period(
        key=f"{period.key}_previous",
        label=f"Previous {period.label}",
        start=new_end - timedelta(days=span - 1),
        end=new_end,
    )
