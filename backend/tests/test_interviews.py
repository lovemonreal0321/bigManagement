"""Interview stage tests: ordering, status/outcome split, multi-event stages."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.domains.applications.service import create_application
from app.domains.interviews.service import (
    add_event,
    create_stage,
    normalise_status_outcome,
    recompute_stage_window,
    reorder_stages,
    set_outcome,
)
from app.domains.interviews.types import stage_badge
from app.enums import ApplicationStatus, InterviewOutcome, InterviewStatus
from app.models import Application, Person, Workspace
from app.schemas.application import ApplicationCreate
from app.schemas.interview import (
    InterviewEventCreate,
    InterviewOutcomeUpdate,
    InterviewStageCreate,
)

S = InterviewStatus
Out = InterviewOutcome


@pytest.fixture
def application(db: Session, workspace: Workspace, make_person) -> Application:
    person: Person = make_person("John Carter")
    return create_application(
        db,
        workspace,
        ApplicationCreate(
            person_id=person.id,
            company_name="Amazon",
            job_title="Senior AI Engineer",
            status=ApplicationStatus.APPLIED,
        ),
    )


def _future(hours: int = 24) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)


class TestStatusOutcomeSplit:
    """Spec §15: status and outcome answer different questions."""

    def test_completed_with_waiting_is_a_valid_combination(self) -> None:
        status, outcome = normalise_status_outcome(S.COMPLETED, Out.WAITING)
        assert status is S.COMPLETED
        assert outcome is Out.WAITING

    def test_completed_without_a_verdict_becomes_waiting(self) -> None:
        status, outcome = normalise_status_outcome(S.COMPLETED, Out.PENDING)
        assert outcome is Out.WAITING

    def test_a_verdict_implies_the_interview_happened(self) -> None:
        status, outcome = normalise_status_outcome(S.SCHEDULED, Out.PASSED)
        assert status is S.COMPLETED
        assert outcome is Out.PASSED

    def test_cancelled_outcome_cancels_the_stage(self) -> None:
        status, _ = normalise_status_outcome(S.SCHEDULED, Out.CANCELLED)
        assert status is S.CANCELLED

    def test_cancelled_status_defaults_the_outcome(self) -> None:
        _, outcome = normalise_status_outcome(S.CANCELLED, Out.PENDING)
        assert outcome is Out.CANCELLED

    def test_no_show_defaults_to_unknown(self) -> None:
        _, outcome = normalise_status_outcome(S.NO_SHOW, Out.PENDING)
        assert outcome is Out.UNKNOWN

    def test_planned_stage_stays_pending(self) -> None:
        status, outcome = normalise_status_outcome(S.PLANNED, Out.PENDING)
        assert status is S.PLANNED
        assert outcome is Out.PENDING


class TestStageBadge:
    """The step tag the design was missing."""

    def test_numbered_round(self) -> None:
        assert stage_badge(2, "Technical") == "R2 · Technical"

    def test_unnumbered_round_shows_the_type_alone(self) -> None:
        assert stage_badge(None, "Recruiter") == "Recruiter"

    def test_round_zero_is_treated_as_unnumbered(self) -> None:
        assert stage_badge(0, "Recruiter") == "Recruiter"


class TestStageOrdering:
    def test_sequence_increments_automatically(
        self, db: Session, workspace: Workspace, application: Application
    ) -> None:
        first = create_stage(
            db, workspace, application.id, InterviewStageCreate(type_key="recruiter_screen")
        )
        second = create_stage(
            db, workspace, application.id, InterviewStageCreate(type_key="technical")
        )
        third = create_stage(
            db, workspace, application.id, InterviewStageCreate(type_key="final")
        )
        assert [first.sequence, second.sequence, third.sequence] == [1, 2, 3]

    def test_screens_are_not_auto_numbered_but_others_are(
        self, db: Session, workspace: Workspace, application: Application
    ) -> None:
        """Spec §14: not every process is numbered, and screens rarely are."""
        screen = create_stage(
            db, workspace, application.id, InterviewStageCreate(type_key="recruiter_screen")
        )
        technical = create_stage(
            db, workspace, application.id, InterviewStageCreate(type_key="technical")
        )
        assert screen.round_number is None
        assert technical.round_number == 1

    def test_explicit_reorder(
        self, db: Session, workspace: Workspace, application: Application
    ) -> None:
        a = create_stage(db, workspace, application.id, InterviewStageCreate(type_key="technical"))
        b = create_stage(db, workspace, application.id, InterviewStageCreate(type_key="final"))
        reordered = reorder_stages(db, workspace, application.id, [b.id, a.id])
        assert [s.id for s in reordered] == [b.id, a.id]
        assert reordered[0].sequence == 1

    def test_reorder_rejects_foreign_stages(
        self, db: Session, workspace: Workspace, application: Application
    ) -> None:
        from app.core.errors import ValidationError

        with pytest.raises(ValidationError):
            reorder_stages(db, workspace, application.id, ["not-a-real-stage-id"])


class TestMultiEventStage:
    """Spec §16: one stage can own several calendar events."""

    def test_final_loop_spans_all_of_its_slots(
        self, db: Session, workspace: Workspace, application: Application
    ) -> None:
        day = _future(48).replace(hour=9, minute=0, second=0, microsecond=0)
        stage = create_stage(
            db,
            workspace,
            application.id,
            InterviewStageCreate(
                type_key="final",
                events=[
                    InterviewEventCreate(
                        title="Behavioral", starts_at=day, ends_at=day + timedelta(hours=1)
                    ),
                    InterviewEventCreate(
                        title="System Design",
                        starts_at=day + timedelta(hours=1),
                        ends_at=day + timedelta(hours=2, minutes=15),
                    ),
                    InterviewEventCreate(
                        title="Hiring Manager",
                        starts_at=day + timedelta(hours=5),
                        ends_at=day + timedelta(hours=5, minutes=45),
                    ),
                ],
            ),
        )
        db.refresh(stage)
        assert len(stage.events) == 3
        assert stage.scheduled_start == day
        assert stage.scheduled_end == day + timedelta(hours=5, minutes=45)
        assert stage.status == S.SCHEDULED.value

    def test_adding_an_event_extends_the_window(
        self, db: Session, workspace: Workspace, application: Application
    ) -> None:
        day = _future(48).replace(minute=0, second=0, microsecond=0)
        stage = create_stage(
            db,
            workspace,
            application.id,
            InterviewStageCreate(
                type_key="panel",
                events=[InterviewEventCreate(starts_at=day, ends_at=day + timedelta(hours=1))],
            ),
        )
        add_event(
            db,
            workspace,
            stage.id,
            InterviewEventCreate(
                starts_at=day + timedelta(hours=3), ends_at=day + timedelta(hours=4)
            ),
        )
        db.refresh(stage)
        assert stage.scheduled_end == day + timedelta(hours=4)

    def test_event_defaults_to_one_hour(
        self, db: Session, workspace: Workspace, application: Application
    ) -> None:
        day = _future(48)
        stage = create_stage(
            db,
            workspace,
            application.id,
            InterviewStageCreate(
                type_key="technical",
                events=[InterviewEventCreate(starts_at=day)],
            ),
        )
        db.refresh(stage)
        assert stage.events[0].ends_at - stage.events[0].starts_at == timedelta(hours=1)

    def test_stage_with_no_events_keeps_a_null_window(
        self, db: Session, workspace: Workspace, application: Application
    ) -> None:
        stage = create_stage(
            db, workspace, application.id, InterviewStageCreate(type_key="final")
        )
        recompute_stage_window(stage)
        assert stage.scheduled_start is None
        assert stage.status == S.PLANNED.value


class TestQuickOutcome:
    """Spec §49: "How did it go?" in one call."""

    def test_marking_passed_completes_the_stage(
        self, db: Session, workspace: Workspace, application: Application
    ) -> None:
        stage = create_stage(
            db,
            workspace,
            application.id,
            InterviewStageCreate(
                type_key="technical",
                events=[InterviewEventCreate(starts_at=_future(-24))],
            ),
        )
        updated = set_outcome(
            db, workspace, stage.id, InterviewOutcomeUpdate(outcome=Out.PASSED)
        )
        assert updated.status == S.COMPLETED.value
        assert updated.outcome == Out.PASSED.value
        assert updated.result_date is not None

    def test_marking_waiting_leaves_no_result_date(
        self, db: Session, workspace: Workspace, application: Application
    ) -> None:
        stage = create_stage(
            db, workspace, application.id, InterviewStageCreate(type_key="technical")
        )
        updated = set_outcome(
            db, workspace, stage.id, InterviewOutcomeUpdate(outcome=Out.WAITING)
        )
        assert updated.status == S.COMPLETED.value
        assert updated.result_date is None

    def test_retracting_a_verdict_clears_the_result_date(
        self, db: Session, workspace: Workspace, application: Application
    ) -> None:
        stage = create_stage(
            db, workspace, application.id, InterviewStageCreate(type_key="technical")
        )
        set_outcome(db, workspace, stage.id, InterviewOutcomeUpdate(outcome=Out.PASSED))
        updated = set_outcome(
            db, workspace, stage.id, InterviewOutcomeUpdate(outcome=Out.WAITING)
        )
        assert updated.result_date is None

    def test_a_note_is_appended(
        self, db: Session, workspace: Workspace, application: Application
    ) -> None:
        stage = create_stage(
            db, workspace, application.id, InterviewStageCreate(type_key="technical")
        )
        updated = set_outcome(
            db,
            workspace,
            stage.id,
            InterviewOutcomeUpdate(outcome=Out.PASSED, note="Went well."),
        )
        assert "Went well." in (updated.notes or "")

    def test_outcome_can_create_the_suggested_follow_up(
        self, db: Session, workspace: Workspace, application: Application
    ) -> None:
        from app.models import FollowUp

        stage = create_stage(
            db,
            workspace,
            application.id,
            InterviewStageCreate(
                type_key="technical",
                events=[InterviewEventCreate(starts_at=_future(-48))],
            ),
        )
        set_outcome(
            db,
            workspace,
            stage.id,
            InterviewOutcomeUpdate(outcome=Out.WAITING, create_follow_up=True),
        )
        follow_ups = db.query(FollowUp).filter(FollowUp.application_id == application.id).all()
        assert len(follow_ups) == 1
        assert follow_ups[0].auto_generated is True


class TestApplicationAutoAdvance:
    def test_scheduling_an_interview_moves_an_applied_application_forward(
        self, db: Session, workspace: Workspace, application: Application
    ) -> None:
        assert application.status == ApplicationStatus.APPLIED.value
        create_stage(
            db,
            workspace,
            application.id,
            InterviewStageCreate(
                type_key="technical",
                events=[InterviewEventCreate(starts_at=_future(72))],
            ),
        )
        db.refresh(application)
        assert application.status == ApplicationStatus.INTERVIEWING.value

    def test_a_decided_application_is_never_dragged_backwards(
        self, db: Session, workspace: Workspace, application: Application
    ) -> None:
        application.status = ApplicationStatus.OFFER.value
        db.commit()
        create_stage(
            db,
            workspace,
            application.id,
            InterviewStageCreate(
                type_key="technical",
                events=[InterviewEventCreate(starts_at=_future(72))],
            ),
        )
        db.refresh(application)
        assert application.status == ApplicationStatus.OFFER.value
