"""Metric formula tests (spec §57: interview pass rate, funnel conversions)."""

from __future__ import annotations

import pytest

from app.domains.analytics import formulas


class TestPassRate:
    def test_counts_only_decided_outcomes(self) -> None:
        rate = formulas.pass_rate(passed=17, failed=8)
        assert rate.numerator == 17
        assert rate.denominator == 25
        assert rate.percent == 68.0

    def test_no_data_is_none_not_zero(self) -> None:
        """"No interviews yet" and "failed every interview" must not look alike."""
        rate = formulas.pass_rate(passed=0, failed=0)
        assert rate.value is None
        assert rate.percent is None

    def test_zero_percent_is_real_when_there_is_data(self) -> None:
        rate = formulas.pass_rate(passed=0, failed=4)
        assert rate.value == 0.0
        assert rate.percent == 0.0

    def test_perfect_rate(self) -> None:
        assert formulas.pass_rate(passed=5, failed=0).percent == 100.0

    def test_meaningfulness_threshold(self) -> None:
        assert not formulas.pass_rate(passed=1, failed=1).is_meaningful
        assert formulas.pass_rate(passed=2, failed=1).is_meaningful

    def test_negative_counts_are_clamped(self) -> None:
        rate = formulas.rate(-5, 10)
        assert rate.numerator == 0


class TestConversions:
    def test_application_to_interview(self) -> None:
        rate = formulas.application_to_interview(31, 120)
        assert rate.percent == 25.8

    def test_first_to_next_round(self) -> None:
        assert formulas.first_to_next_round(18, 28).percent == 64.3

    def test_final_to_offer(self) -> None:
        assert formulas.final_to_offer(3, 8).percent == 37.5

    def test_application_to_offer(self) -> None:
        assert formulas.application_to_offer(3, 120).percent == 2.5

    def test_offer_acceptance(self) -> None:
        assert formulas.offer_acceptance(2, 3).percent == 66.7

    def test_conversion_from_empty_previous_step(self) -> None:
        assert formulas.conversion_between(0, 0).value is None


class TestRateSerialisation:
    def test_carries_numerator_and_denominator(self) -> None:
        """Spec §27: always show the fraction next to the percentage."""
        payload = formulas.pass_rate(17, 8).as_dict()
        assert payload["numerator"] == 17
        assert payload["denominator"] == 25
        assert payload["percent"] == 68.0
        assert payload["is_meaningful"] is True


@pytest.mark.parametrize(
    ("passed", "failed", "expected"),
    [(1, 0, 100.0), (0, 1, 0.0), (2, 2, 50.0), (1, 2, 33.3), (2, 1, 66.7)],
)
def test_rounding_is_one_decimal(passed: int, failed: int, expected: float) -> None:
    assert formulas.pass_rate(passed, failed).percent == expected
