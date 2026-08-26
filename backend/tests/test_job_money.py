"""Salary conversion and payday projection.

Pure arithmetic, but the arithmetic is where pay tracking goes wrong: bi-weekly
and semi-monthly are not the same thing, and a payday on the 31st has to
survive February.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domains.jobs.money import (
    annual_from_hourly,
    derive_amounts,
    gross_per_paycheck,
    hourly_from_annual,
    pay_dates,
)
from app.enums import PayPeriod, SalaryType


class TestConversion:
    def test_hourly_to_annual_on_the_standard_basis(self) -> None:
        assert annual_from_hourly(85, 40, 52) == 176_800.0

    def test_annual_to_hourly_round_trips(self) -> None:
        assert hourly_from_annual(176_800, 40, 52) == 85.0

    def test_part_time_uses_its_own_basis(self) -> None:
        """32 hours is not 40 — the whole reason the basis is per job."""
        assert annual_from_hourly(85, 32, 52) == 141_440.0

    def test_zero_hours_does_not_divide_by_zero(self) -> None:
        assert hourly_from_annual(100_000, 0, 52) == 0.0


class TestDeriveAmounts:
    def test_an_hourly_job_gets_its_annual_filled_in(self) -> None:
        annual, hourly = derive_amounts(
            salary_type=SalaryType.HOURLY.value,
            annual_amount=None,
            hourly_amount=85,
            hours_per_week=40,
            weeks_per_year=52,
        )
        assert (annual, hourly) == (176_800.0, 85)

    def test_an_annual_job_gets_its_hourly_filled_in(self) -> None:
        annual, hourly = derive_amounts(
            salary_type=SalaryType.ANNUAL.value,
            annual_amount=176_800,
            hourly_amount=None,
            hours_per_week=40,
            weeks_per_year=52,
        )
        assert (annual, hourly) == (176_800, 85.0)

    def test_a_hand_corrected_figure_is_not_recomputed_away(self) -> None:
        """The user overrode the derived annual; keep what they typed."""
        annual, hourly = derive_amounts(
            salary_type=SalaryType.HOURLY.value,
            annual_amount=180_000,
            hourly_amount=85,
            hours_per_week=40,
            weeks_per_year=52,
        )
        assert annual == 180_000

    def test_missing_amounts_stay_missing(self) -> None:
        assert derive_amounts(
            salary_type=SalaryType.ANNUAL.value,
            annual_amount=None,
            hourly_amount=None,
            hours_per_week=40,
            weeks_per_year=52,
        ) == (None, None)


class TestPaycheckSize:
    @pytest.mark.parametrize(
        ("period", "expected"),
        [
            (PayPeriod.WEEKLY.value, 2_000.0),
            (PayPeriod.BIWEEKLY.value, 4_000.0),
            (PayPeriod.SEMIMONTHLY.value, 4_333.33),
            (PayPeriod.MONTHLY.value, 8_666.67),
        ],
    )
    def test_each_period_divides_the_year_correctly(
        self, period: str, expected: float
    ) -> None:
        assert gross_per_paycheck(104_000, period) == expected

    def test_semimonthly_pays_more_per_cheque_than_biweekly(self) -> None:
        """24 cheques a year, not 26 — people notice this on payday."""
        semi = gross_per_paycheck(104_000, PayPeriod.SEMIMONTHLY.value)
        bi = gross_per_paycheck(104_000, PayPeriod.BIWEEKLY.value)
        assert semi is not None and bi is not None and semi > bi

    def test_no_salary_means_no_figure_rather_than_zero(self) -> None:
        assert gross_per_paycheck(None, PayPeriod.MONTHLY.value) is None


class TestPayDates:
    def test_weekly(self) -> None:
        assert pay_dates(date(2026, 9, 4), PayPeriod.WEEKLY.value, count=3) == [
            date(2026, 9, 4),
            date(2026, 9, 11),
            date(2026, 9, 18),
        ]

    def test_biweekly(self) -> None:
        assert pay_dates(date(2026, 9, 4), PayPeriod.BIWEEKLY.value, count=3) == [
            date(2026, 9, 4),
            date(2026, 9, 18),
            date(2026, 10, 2),
        ]

    def test_monthly(self) -> None:
        assert pay_dates(date(2026, 9, 15), PayPeriod.MONTHLY.value, count=3) == [
            date(2026, 9, 15),
            date(2026, 10, 15),
            date(2026, 11, 15),
        ]

    def test_monthly_on_the_31st_survives_a_short_month(self) -> None:
        """The 31st + one month is the 30th, not a skip into the next month."""
        dates = pay_dates(date(2026, 1, 31), PayPeriod.MONTHLY.value, count=4)
        assert dates == [
            date(2026, 1, 31),
            date(2026, 2, 28),
            date(2026, 3, 31),
            date(2026, 4, 30),
        ]

    def test_semimonthly_lands_twice_a_month(self) -> None:
        dates = pay_dates(date(2026, 9, 1), PayPeriod.SEMIMONTHLY.value, count=4)
        assert dates == [
            date(2026, 9, 1),
            date(2026, 9, 16),
            date(2026, 10, 1),
            date(2026, 10, 16),
        ]

    def test_after_skips_paydays_already_gone(self) -> None:
        dates = pay_dates(
            date(2026, 1, 2),
            PayPeriod.BIWEEKLY.value,
            count=2,
            after=date(2026, 8, 26),
        )
        assert all(d > date(2026, 8, 26) for d in dates)
        assert len(dates) == 2

    def test_until_stops_the_run(self) -> None:
        """An ended job stops paying."""
        dates = pay_dates(
            date(2026, 9, 4),
            PayPeriod.WEEKLY.value,
            count=10,
            until=date(2026, 9, 20),
        )
        assert dates == [date(2026, 9, 4), date(2026, 9, 11), date(2026, 9, 18)]

    def test_zero_count_is_empty(self) -> None:
        assert pay_dates(date(2026, 9, 4), PayPeriod.WEEKLY.value, count=0) == []

    def test_a_long_gone_start_date_still_terminates(self) -> None:
        """Years of past paydays must not spin or blow up."""
        dates = pay_dates(
            date(2005, 1, 7),
            PayPeriod.WEEKLY.value,
            count=3,
            after=date(2026, 8, 26),
        )
        assert len(dates) == 3
        assert all(d > date(2026, 8, 26) for d in dates)
