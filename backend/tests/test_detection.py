"""Interview-detection heuristic tests (spec §8, §57)."""

from __future__ import annotations

import pytest

from app.domains.calendar.detection import SUGGESTION_THRESHOLD, detect
from app.enums import InterviewTypeKey


class TestPositiveSignals:
    def test_plain_interview_title(self) -> None:
        result = detect(title="Amazon — Technical Interview")
        assert result.is_suggestion
        assert result.suggested_type == InterviewTypeKey.TECHNICAL.value

    def test_recruiter_screen(self) -> None:
        result = detect(title="Recruiter Screen with Stripe")
        assert result.is_suggestion
        assert result.suggested_type == InterviewTypeKey.RECRUITER_SCREEN.value

    def test_system_design_round(self) -> None:
        result = detect(title="Final round — System Design")
        assert result.is_suggestion
        assert result.suggested_type == InterviewTypeKey.SYSTEM_DESIGN.value

    def test_assessment_link_alone_is_strong(self) -> None:
        result = detect(
            title="Take the exercise",
            description="Complete at https://app.codesignal.com/test/abc",
        )
        assert result.is_suggestion
        assert any("assessment platform" in r for r in result.reasons)

    def test_invite_from_an_ats(self) -> None:
        result = detect(
            title="Chat about the role",
            organizer_email="no-reply@greenhouse.io",
        )
        assert result.is_suggestion

    def test_recruiter_organizer_name(self) -> None:
        result = detect(
            title="Intro call", organizer_name="Priya Sharma (Talent Acquisition)"
        )
        assert result.score > 0


class TestNegativeSignals:
    @pytest.mark.parametrize(
        "title",
        [
            "Team standup",
            "Sprint retro",
            "All hands",
            "Lunch with Sam",
            "Dentist",
            "Focus time",
            "1:1 with manager",
            "Weekly sync",
        ],
    )
    def test_routine_meetings_are_not_suggested(self, title: str) -> None:
        assert not detect(title=title).is_suggestion

    def test_negative_beats_an_incidental_keyword(self) -> None:
        """"Coding standup" is a standup, not a coding interview."""
        result = detect(title="Coding standup")
        assert not result.is_suggestion

    def test_empty_event(self) -> None:
        result = detect(title=None)
        assert result.score == 0.0
        assert not result.is_suggestion


class TestExtraction:
    def test_company_from_a_dashed_title(self) -> None:
        assert detect(title="Amazon — Technical Interview").suggested_company == "Amazon"

    def test_company_from_a_bracket_style_title(self) -> None:
        result = detect(title="Anthropic <> John Carter")
        assert result.suggested_company == "Anthropic"

    def test_company_from_the_organiser_domain(self) -> None:
        result = detect(
            title="Interview", organizer_email="recruiting@datadoghq.com"
        )
        assert result.suggested_company == "Datadoghq"

    def test_generic_mail_domain_gives_no_company(self) -> None:
        result = detect(title="Interview", organizer_email="someone@gmail.com")
        assert result.suggested_company is None

    def test_ats_domain_gives_no_company(self) -> None:
        """greenhouse.io is the scheduling tool, not the employer."""
        result = detect(title="Interview", organizer_email="x@greenhouse.io")
        assert result.suggested_company is None

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Interview Round 2", 2),
            ("Amazon R3 — Final", 3),
            ("Technical interview", None),
        ],
    )
    def test_round_extraction(self, title: str, expected: int | None) -> None:
        assert detect(title=title).suggested_round == expected


def test_score_is_bounded() -> None:
    result = detect(
        title="Final round technical interview coding system design hiring manager",
        description="interview interview interview",
        organizer_email="x@greenhouse.io",
    )
    assert 0.0 <= result.score <= 1.0


def test_reasons_are_capped_for_display() -> None:
    result = detect(
        title="Final round technical interview coding system design panel candidate",
        description="recruiter screening assessment hiring",
    )
    assert len(result.reasons) <= 6


def test_threshold_is_documented_and_used() -> None:
    assert 0 < SUGGESTION_THRESHOLD < 1
    assert detect(title="Technical Interview").score >= SUGGESTION_THRESHOLD
