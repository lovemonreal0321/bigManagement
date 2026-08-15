"""Timezone and business-day tests (spec §44, §57)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.core.timeutils import (
    add_business_days,
    business_days_between,
    day_bounds,
    local_date,
    overlaps,
    start_of_week,
    to_tz,
    to_utc,
)


class TestTimezoneConversion:
    def test_aware_datetime_converts_to_utc(self) -> None:
        value = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
        assert to_utc(value) == value

    def test_naive_datetime_uses_the_given_zone_not_the_server(self) -> None:
        """A naive value must never be silently read as server-local time."""
        naive = datetime(2026, 8, 14, 10, 0)
        result = to_utc(naive, assume_tz="America/New_York")
        # 10:00 EDT (UTC-4 in August) is 14:00 UTC.
        assert result == datetime(2026, 8, 14, 14, 0, tzinfo=UTC)

    def test_naive_defaults_to_utc_when_no_zone_given(self) -> None:
        naive = datetime(2026, 8, 14, 10, 0)
        assert to_utc(naive) == datetime(2026, 8, 14, 10, 0, tzinfo=UTC)

    def test_render_in_display_timezone(self) -> None:
        instant = datetime(2026, 8, 14, 14, 0, tzinfo=UTC)
        assert to_tz(instant, "America/New_York").hour == 10
        assert to_tz(instant, "Europe/Berlin").hour == 16

    def test_local_date_can_differ_from_utc_date(self) -> None:
        """23:00 in New York is already the next day in UTC."""
        instant = datetime(2026, 8, 15, 3, 0, tzinfo=UTC)
        assert instant.date() == date(2026, 8, 15)
        assert local_date(instant, "America/New_York") == date(2026, 8, 14)

    def test_unknown_timezone_falls_back_to_utc(self) -> None:
        instant = datetime(2026, 8, 14, 14, 0, tzinfo=UTC)
        assert to_tz(instant, "Mars/Olympus_Mons").hour == 14

    def test_day_bounds_span_a_local_day(self) -> None:
        start, end = day_bounds(date(2026, 8, 14), "America/New_York")
        assert start == datetime(2026, 8, 14, 4, 0, tzinfo=UTC)
        assert end == datetime(2026, 8, 15, 4, 0, tzinfo=UTC)

    def test_day_bounds_handle_a_dst_transition(self) -> None:
        """US DST ends 2026-11-01, making that local day 25 hours long."""
        start, end = day_bounds(date(2026, 11, 1), "America/New_York")
        assert (end - start).total_seconds() == 25 * 3600


class TestBusinessDays:
    def test_adds_weekdays(self) -> None:
        # Monday 2026-08-10 + 3 business days -> Thursday.
        assert add_business_days(date(2026, 8, 10), 3) == date(2026, 8, 13)

    def test_skips_the_weekend(self) -> None:
        # Friday 2026-08-14 + 1 business day -> Monday 2026-08-17.
        assert add_business_days(date(2026, 8, 14), 1) == date(2026, 8, 17)

    def test_spec_example_three_business_days(self) -> None:
        """Spec §20: interview on Aug 11 -> follow-up suggested Aug 14."""
        # 2026-08-11 is a Tuesday; +3 business days is Friday the 14th.
        assert add_business_days(date(2026, 8, 11), 3) == date(2026, 8, 14)

    def test_zero_is_identity(self) -> None:
        assert add_business_days(date(2026, 8, 14), 0) == date(2026, 8, 14)

    def test_negative_walks_backwards(self) -> None:
        assert add_business_days(date(2026, 8, 17), -1) == date(2026, 8, 14)

    def test_counting_between_dates(self) -> None:
        assert business_days_between(date(2026, 8, 10), date(2026, 8, 17)) == 5

    def test_counting_is_signed(self) -> None:
        assert business_days_between(date(2026, 8, 17), date(2026, 8, 10)) == -5


class TestWeekStart:
    def test_monday_based_by_default(self) -> None:
        assert start_of_week(date(2026, 8, 14)) == date(2026, 8, 10)

    def test_sunday_based(self) -> None:
        assert start_of_week(date(2026, 8, 14), week_starts_on=6) == date(2026, 8, 9)


class TestOverlap:
    def _dt(self, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 8, 14, hour, minute, tzinfo=UTC)

    def test_partial_overlap(self) -> None:
        assert overlaps(
            self._dt(10), self._dt(11), self._dt(10, 30), self._dt(11, 30)
        )

    def test_back_to_back_is_not_an_overlap(self) -> None:
        """A 10-11 meeting followed by an 11-12 meeting is a normal schedule."""
        assert not overlaps(self._dt(10), self._dt(11), self._dt(11), self._dt(12))

    def test_containment_counts(self) -> None:
        assert overlaps(self._dt(9), self._dt(12), self._dt(10), self._dt(11))

    def test_disjoint(self) -> None:
        assert not overlaps(self._dt(9), self._dt(10), self._dt(14), self._dt(15))


@pytest.mark.parametrize(
    ("tz_name", "expected_hour"),
    [("UTC", 14), ("America/New_York", 10), ("America/Chicago", 9), ("Asia/Tokyo", 23)],
)
def test_same_instant_across_zones(tz_name: str, expected_hour: int) -> None:
    instant = datetime(2026, 8, 14, 14, 0, tzinfo=UTC)
    assert to_tz(instant, tz_name).hour == expected_hour
