"""Analytics computed from real rows (spec §54, §57).

These guard the definitions, not just the arithmetic: the pass-rate denominator
must exclude undecided outcomes, and the funnel must count applications rather
than interviews.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.domains.analytics.periods import Period, previous_period, resolve_period
from app.domains.analytics.service import compute_analytics
from app.domains.applications.service import create_application
from app.domains.interviews.service import create_stage
from app.enums import ApplicationStatus, InterviewOutcome, InterviewStatus
from app.models import Person, Workspace
from app.schemas.application import ApplicationCreate
from app.schemas.interview import InterviewEventCreate, InterviewStageCreate

ALL_TIME = Period("all_time", "All Time", None, None)
S = InterviewStatus
Out = InterviewOutcome


@pytest.fixture
def john(make_person) -> Person:
    return make_person("John Carter")


def _make(
    db: Session,
    workspace: Workspace,
    person: Person,
    company: str,
    *,
    status: ApplicationStatus = ApplicationStatus.APPLIED,
    applied_days_ago: int = 10,
    stages: list[tuple[str, InterviewStatus, InterviewOutcome]] | None = None,
    scheduled: bool = True,
):
    application = create_application(
        db,
        workspace,
        ApplicationCreate(
            person_id=person.id,
            company_name=company,
            job_title="Engineer",
            status=status,
            applied_date=date.today() - timedelta(days=applied_days_ago),
        ),
    )
    for type_key, stage_status, outcome in stages or []:
        events = (
            [
                InterviewEventCreate(
                    starts_at=datetime.now(UTC)
                    - timedelta(days=applied_days_ago - 2)
                )
            ]
            if scheduled
            else []
        )
        create_stage(
            db,
            workspace,
            application.id,
            InterviewStageCreate(
                type_key=type_key,
                status=stage_status,
                outcome=outcome,
                events=events,
            ),
        )
    # Auto-advance may have moved the status; restore what the test asked for.
    db.refresh(application)
    application.status = status.value
    db.commit()
    return application


class TestPassRateDenominator:
    def test_only_passed_and_failed_count(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        """Spec §54: scheduled/waiting/cancelled must not dilute the rate."""
        _make(
            db,
            workspace,
            john,
            "Amazon",
            stages=[
                ("technical", S.COMPLETED, Out.PASSED),
                ("technical", S.COMPLETED, Out.PASSED),
                ("technical", S.COMPLETED, Out.FAILED),
                ("technical", S.COMPLETED, Out.WAITING),
                ("technical", S.SCHEDULED, Out.PENDING),
                ("technical", S.CANCELLED, Out.CANCELLED),
            ],
        )
        result = compute_analytics(db, workspace, [john], ALL_TIME)
        rate = result.conversions.interview_pass_rate
        assert rate.numerator == 2
        assert rate.denominator == 3
        assert rate.percent == 66.7

    def test_no_decided_outcomes_gives_no_rate(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _make(
            db,
            workspace,
            john,
            "Meta",
            stages=[("technical", S.SCHEDULED, Out.PENDING)],
        )
        rate = compute_analytics(db, workspace, [john], ALL_TIME).conversions.interview_pass_rate
        assert rate.denominator == 0
        assert rate.percent is None

    def test_technical_rate_only_counts_technical_types(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _make(
            db,
            workspace,
            john,
            "Amazon",
            stages=[
                ("technical", S.COMPLETED, Out.PASSED),
                ("system_design", S.COMPLETED, Out.FAILED),
                ("behavioral", S.COMPLETED, Out.PASSED),
                ("recruiter_screen", S.COMPLETED, Out.PASSED),
            ],
        )
        result = compute_analytics(db, workspace, [john], ALL_TIME)
        technical = result.conversions.technical_pass_rate
        assert technical.numerator == 1
        assert technical.denominator == 2
        # ... while the overall rate sees all four.
        assert result.conversions.interview_pass_rate.denominator == 4


class TestApplicationToInterview:
    def test_counts_applications_not_interviews(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        """One application with three rounds still converts exactly once."""
        _make(
            db,
            workspace,
            john,
            "Amazon",
            stages=[
                ("recruiter_screen", S.COMPLETED, Out.PASSED),
                ("technical", S.COMPLETED, Out.PASSED),
                ("final", S.COMPLETED, Out.PASSED),
            ],
        )
        _make(db, workspace, john, "Google")
        _make(db, workspace, john, "Apple")
        _make(db, workspace, john, "Meta")

        rate = compute_analytics(
            db, workspace, [john], ALL_TIME
        ).conversions.application_to_interview
        assert rate.numerator == 1
        assert rate.denominator == 4
        assert rate.percent == 25.0

    def test_a_planned_stage_is_not_a_conversion(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        """A placeholder step in the timeline is not evidence of an interview."""
        _make(
            db,
            workspace,
            john,
            "Amazon",
            stages=[("final", S.PLANNED, Out.PENDING)],
            scheduled=False,
        )
        rate = compute_analytics(
            db, workspace, [john], ALL_TIME
        ).conversions.application_to_interview
        assert rate.numerator == 0

    def test_a_screen_does_count_as_an_interview(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _make(
            db,
            workspace,
            john,
            "Amazon",
            stages=[("recruiter_screen", S.COMPLETED, Out.PASSED)],
        )
        rate = compute_analytics(
            db, workspace, [john], ALL_TIME
        ).conversions.application_to_interview
        assert rate.numerator == 1


class TestFunnel:
    def test_steps_are_monotonically_narrowing(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _make(db, workspace, john, "NoInterview1")
        _make(db, workspace, john, "NoInterview2")
        _make(
            db,
            workspace,
            john,
            "OneRound",
            stages=[("recruiter_screen", S.COMPLETED, Out.FAILED)],
        )
        _make(
            db,
            workspace,
            john,
            "TwoRounds",
            stages=[
                ("recruiter_screen", S.COMPLETED, Out.PASSED),
                ("technical", S.COMPLETED, Out.FAILED),
            ],
        )
        _make(
            db,
            workspace,
            john,
            "WentAllTheWay",
            status=ApplicationStatus.OFFER,
            stages=[
                ("recruiter_screen", S.COMPLETED, Out.PASSED),
                ("technical", S.COMPLETED, Out.PASSED),
                ("final", S.COMPLETED, Out.PASSED),
            ],
        )

        funnel = {
            step.key: step.count
            for step in compute_analytics(db, workspace, [john], ALL_TIME).funnel
        }
        assert funnel["applied"] == 5
        assert funnel["first_interview"] == 3
        assert funnel["second_round"] == 2
        assert funnel["final"] == 1
        assert funnel["offer"] == 1

    def test_conversions_between_steps(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        for i in range(4):
            _make(db, workspace, john, f"Quiet{i}")
        _make(
            db,
            workspace,
            john,
            "Live",
            stages=[("technical", S.COMPLETED, Out.PASSED)],
        )
        steps = compute_analytics(db, workspace, [john], ALL_TIME).funnel
        first = next(s for s in steps if s.key == "first_interview")
        assert first.conversion_from_previous is not None
        assert first.conversion_from_previous.percent == 20.0


class TestOfferDetection:
    def test_a_current_offer_status_counts(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _make(db, workspace, john, "Datadog", status=ApplicationStatus.OFFER)
        assert compute_analytics(db, workspace, [john], ALL_TIME).volume.offers == 1

    def test_an_accepted_application_counts_as_an_offer(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _make(db, workspace, john, "Spotify", status=ApplicationStatus.ACCEPTED)
        result = compute_analytics(db, workspace, [john], ALL_TIME)
        assert result.volume.offers == 1
        assert result.volume.accepted == 1
        assert result.conversions.offer_acceptance.percent == 100.0

    def test_a_declined_offer_is_still_an_offer(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        """An offer the candidate turned down ends up `withdrawn`; the funnel
        must still credit the offer, which is why the activity log is consulted.
        """
        from app.domains.applications.service import change_status

        application = _make(db, workspace, john, "Stripe")
        change_status(db, workspace, application.id, status=ApplicationStatus.OFFER)
        change_status(db, workspace, application.id, status=ApplicationStatus.WITHDRAWN)

        result = compute_analytics(db, workspace, [john], ALL_TIME)
        assert result.volume.offers == 1
        assert result.volume.accepted == 0


class TestPersonScoping:
    def test_numbers_are_isolated_per_person(
        self, db: Session, workspace: Workspace, make_person
    ) -> None:
        john = make_person("John Carter")
        david = make_person("David Okafor", color="#db2777")

        _make(db, workspace, john, "Amazon", stages=[("technical", S.COMPLETED, Out.PASSED)])
        _make(db, workspace, john, "Meta")
        _make(db, workspace, david, "Microsoft", stages=[("technical", S.COMPLETED, Out.FAILED)])

        john_only = compute_analytics(db, workspace, [john], ALL_TIME)
        david_only = compute_analytics(db, workspace, [david], ALL_TIME)
        both = compute_analytics(db, workspace, [john, david], ALL_TIME)

        assert john_only.volume.applications == 2
        assert david_only.volume.applications == 1
        assert both.volume.applications == 3
        assert john_only.conversions.interview_pass_rate.percent == 100.0
        assert david_only.conversions.interview_pass_rate.percent == 0.0
        assert both.conversions.interview_pass_rate.percent == 50.0

    def test_comparison_rows_appear_for_multiple_people(
        self, db: Session, workspace: Workspace, make_person
    ) -> None:
        john = make_person("John Carter")
        david = make_person("David Okafor", color="#db2777")
        _make(db, workspace, john, "Amazon")
        _make(db, workspace, david, "Microsoft")

        result = compute_analytics(db, workspace, [john, david], ALL_TIME)
        assert len(result.comparison) == 2
        assert {r.person_name for r in result.comparison} == {"John", "David"}

    def test_no_people_selected_returns_zeroes_not_an_error(
        self, db: Session, workspace: Workspace
    ) -> None:
        result = compute_analytics(db, workspace, [], ALL_TIME)
        assert result.volume.applications == 0
        assert result.conversions.interview_pass_rate.percent is None


class TestPeriods:
    def test_application_cohort_respects_the_window(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _make(db, workspace, john, "Recent", applied_days_ago=5)
        _make(db, workspace, john, "Old", applied_days_ago=90)

        today = date.today()
        last_30 = resolve_period("last_30_days", today=today)
        assert compute_analytics(db, workspace, [john], last_30).volume.applications == 1
        assert compute_analytics(db, workspace, [john], ALL_TIME).volume.applications == 2

    def test_a_recent_application_is_not_penalised_for_old_interviews(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        """Cohort semantics: interviews are counted whenever they happened, so
        the conversion rate is not skewed by where the window happens to fall.
        """
        _make(
            db,
            workspace,
            john,
            "Amazon",
            applied_days_ago=3,
            stages=[("technical", S.COMPLETED, Out.PASSED)],
        )
        last_7 = resolve_period("last_7_days", today=date.today())
        result = compute_analytics(db, workspace, [john], last_7)
        assert result.conversions.application_to_interview.percent == 100.0

    def test_custom_range_requires_both_ends(self) -> None:
        from app.core.errors import ValidationError

        with pytest.raises(ValidationError):
            resolve_period("custom", today=date.today(), start=date.today())

    def test_custom_range_rejects_a_backwards_window(self) -> None:
        from app.core.errors import ValidationError

        with pytest.raises(ValidationError):
            resolve_period(
                "custom",
                today=date.today(),
                start=date(2026, 8, 20),
                end=date(2026, 8, 10),
            )

    def test_unknown_period_falls_back_to_all_time(self) -> None:
        period = resolve_period("nonsense", today=date.today())
        assert period.key == "all_time"
        assert period.start is None

    def test_previous_period_is_the_same_length(self) -> None:
        period = resolve_period("last_30_days", today=date(2026, 8, 14))
        previous = previous_period(period)
        assert previous is not None
        assert (previous.end - previous.start).days == (period.end - period.start).days
        assert previous.end == period.start - timedelta(days=1)

    def test_all_time_has_no_previous_period(self) -> None:
        assert previous_period(ALL_TIME) is None


def test_by_type_reports_numerator_and_denominator(
    db: Session, workspace: Workspace, john: Person
) -> None:
    """Spec §27: show "17 / 25 passed", not a bare percentage."""
    _make(
        db,
        workspace,
        john,
        "Amazon",
        stages=[
            ("technical", S.COMPLETED, Out.PASSED),
            ("technical", S.COMPLETED, Out.PASSED),
            ("technical", S.COMPLETED, Out.FAILED),
            ("technical", S.SCHEDULED, Out.PENDING),
        ],
    )
    rows = compute_analytics(db, workspace, [john], ALL_TIME).by_type
    technical = next(r for r in rows if r.type_key == "technical")
    assert technical.passed == 2
    assert technical.failed == 1
    assert technical.total_decided == 3
    assert technical.scheduled == 1
    assert technical.rate.percent == 66.7
    assert technical.rate.is_meaningful is True
