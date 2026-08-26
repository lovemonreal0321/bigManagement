"""Salary conversion and payday projection.

Pure functions, no database. Two things people get wrong about pay that this is
careful about:

* **Semi-monthly is not bi-weekly.** 24 cheques a year, not 26. Someone paid on
  the 1st and 15th gets a noticeably larger cheque than someone paid every
  fortnight on the same salary, and projecting the wrong one is a real error.
* **Hourly → annual needs a stated basis.** 40 x 52 is only right for a
  full-time year. The basis is stored per job and shown in the UI rather than
  buried in a constant.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from app.enums import PAY_PERIODS_PER_YEAR, PayPeriod, SalaryType


def annual_from_hourly(
    hourly: float, hours_per_week: float, weeks_per_year: float
) -> float:
    return round(hourly * hours_per_week * weeks_per_year, 2)


def hourly_from_annual(
    annual: float, hours_per_week: float, weeks_per_year: float
) -> float:
    hours = hours_per_week * weeks_per_year
    if hours <= 0:
        return 0.0
    return round(annual / hours, 2)


def derive_amounts(
    *,
    salary_type: str,
    annual_amount: float | None,
    hourly_amount: float | None,
    hours_per_week: float,
    weeks_per_year: float,
) -> tuple[float | None, float | None]:
    """Fill in whichever figure was not typed.

    The quoted figure wins. If the user typed an annual salary, the hourly rate
    is derived from it and vice versa — but an explicitly supplied counterpart
    is left alone, so a hand-corrected figure is not recomputed away.
    """
    if salary_type == SalaryType.HOURLY.value:
        if hourly_amount is None:
            return annual_amount, None
        derived = annual_from_hourly(hourly_amount, hours_per_week, weeks_per_year)
        return (annual_amount if annual_amount is not None else derived), hourly_amount

    if annual_amount is None:
        return None, hourly_amount
    derived = hourly_from_annual(annual_amount, hours_per_week, weeks_per_year)
    return annual_amount, (hourly_amount if hourly_amount is not None else derived)


def gross_per_paycheck(annual_amount: float | None, pay_period: str) -> float | None:
    """What one cheque is worth, before deductions.

    Gross only — this app knows nothing about the person's tax position, and a
    confidently wrong net figure would be worse than none.
    """
    if annual_amount is None:
        return None
    periods = PAY_PERIODS_PER_YEAR.get(pay_period)
    if not periods:
        return None
    return round(annual_amount / periods, 2)


def _add_months(day: date, months: int) -> date:
    """Move by whole months, clamping to the end of a short month.

    The 31st plus one month is the 28th/30th, not a rollover into the next
    month — a payday on the 31st should not skip February.
    """
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def pay_dates(
    first_pay_date: date,
    pay_period: str,
    *,
    count: int,
    after: date | None = None,
    until: date | None = None,
) -> list[date]:
    """Paydays from `first_pay_date` onwards.

    `after` skips dates already past, so the caller gets upcoming paydays rather
    than a history. `until` stops the run early — an ended job stops paying.
    """
    if count <= 0:
        return []

    dates: list[date] = []
    current = first_pay_date
    # A long-running job can have hundreds of past paydays before the window of
    # interest; walk them without emitting, and stop rather than loop forever.
    for step in range(10_000):
        if until is not None and current > until:
            break
        if after is None or current > after:
            dates.append(current)
            if len(dates) >= count:
                break

        if pay_period == PayPeriod.WEEKLY.value:
            current = current + timedelta(days=7)
        elif pay_period == PayPeriod.BIWEEKLY.value:
            current = current + timedelta(days=14)
        elif pay_period == PayPeriod.MONTHLY.value:
            current = _add_months(first_pay_date, step + 1)
        elif pay_period == PayPeriod.SEMIMONTHLY.value:
            # The same two days each month, a fortnight apart in practice.
            current = (
                current + timedelta(days=15)
                if current.day < 16
                else _add_months(current.replace(day=max(current.day - 15, 1)), 1)
            )
        else:
            break

    return dates
