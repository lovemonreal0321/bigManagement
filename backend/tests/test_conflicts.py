"""Scheduling-conflict tests (spec §43, §57).

The rule under test: conflicts exist only *within* a person, never between two
different people.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.domains.applications.service import create_application
from app.domains.calendar.conflicts import find_conflicts
from app.domains.interviews.service import create_stage
from app.enums import EventClassification
from app.models import CalendarEvent, Person, Workspace
from app.schemas.application import ApplicationCreate
from app.schemas.interview import InterviewEventCreate, InterviewStageCreate

BASE = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)
WINDOW_START = BASE - timedelta(days=1)
WINDOW_END = BASE + timedelta(days=2)


def _book(
    db: Session,
    workspace: Workspace,
    person: Person,
    company: str,
    start: datetime,
    minutes: int = 60,
) -> None:
    application = create_application(
        db,
        workspace,
        ApplicationCreate(
            person_id=person.id, company_name=company, job_title="Engineer"
        ),
    )
    create_stage(
        db,
        workspace,
        application.id,
        InterviewStageCreate(
            type_key="technical",
            events=[
                InterviewEventCreate(
                    starts_at=start, ends_at=start + timedelta(minutes=minutes)
                )
            ],
        ),
    )


@pytest.fixture
def john(make_person) -> Person:
    return make_person("John Carter", color="#2563eb")


@pytest.fixture
def david(make_person) -> Person:
    return make_person("David Okafor", color="#db2777")


class TestSamePersonConflicts:
    def test_overlapping_interviews_are_flagged(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _book(db, workspace, john, "Amazon", BASE)
        _book(db, workspace, john, "Microsoft", BASE + timedelta(minutes=30))

        conflicts = find_conflicts(
            db, workspace, [john], start=WINDOW_START, end=WINDOW_END
        )
        assert len(conflicts) == 1
        assert conflicts[0].person_id == john.id
        assert conflicts[0].overlap_minutes == 30

    def test_back_to_back_interviews_are_fine(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _book(db, workspace, john, "Amazon", BASE)
        _book(db, workspace, john, "Microsoft", BASE + timedelta(hours=1))
        assert (
            find_conflicts(db, workspace, [john], start=WINDOW_START, end=WINDOW_END)
            == []
        )

    def test_a_contained_interview_conflicts(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _book(db, workspace, john, "Amazon", BASE, minutes=180)
        _book(db, workspace, john, "Meta", BASE + timedelta(minutes=60), minutes=30)
        conflicts = find_conflicts(
            db, workspace, [john], start=WINDOW_START, end=WINDOW_END
        )
        assert len(conflicts) == 1
        assert conflicts[0].overlap_minutes == 30

    def test_three_overlapping_interviews_give_three_pairs(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _book(db, workspace, john, "Amazon", BASE, minutes=120)
        _book(db, workspace, john, "Meta", BASE + timedelta(minutes=15), minutes=120)
        _book(db, workspace, john, "Google", BASE + timedelta(minutes=30), minutes=120)
        conflicts = find_conflicts(
            db, workspace, [john], start=WINDOW_START, end=WINDOW_END
        )
        assert len(conflicts) == 3


class TestDifferentPeople:
    def test_two_people_at_the_same_time_is_not_a_conflict(
        self, db: Session, workspace: Workspace, john: Person, david: Person
    ) -> None:
        """Spec §43: John at 10 and David at 10 is the normal state of things."""
        _book(db, workspace, john, "Amazon", BASE)
        _book(db, workspace, david, "Microsoft", BASE)

        conflicts = find_conflicts(
            db, workspace, [john, david], start=WINDOW_START, end=WINDOW_END
        )
        assert conflicts == []

    def test_only_the_clashing_person_is_reported(
        self, db: Session, workspace: Workspace, john: Person, david: Person
    ) -> None:
        _book(db, workspace, john, "Amazon", BASE)
        _book(db, workspace, john, "Meta", BASE + timedelta(minutes=30))
        _book(db, workspace, david, "Microsoft", BASE)

        conflicts = find_conflicts(
            db, workspace, [john, david], start=WINDOW_START, end=WINDOW_END
        )
        assert len(conflicts) == 1
        assert conflicts[0].person_id == john.id


class TestExternalEvents:
    def _external(
        self,
        db: Session,
        person: Person,
        title: str,
        start: datetime,
        classification: EventClassification,
        minutes: int = 60,
    ) -> CalendarEvent:
        event = CalendarEvent(
            person_id=person.id,
            title=title,
            starts_at=start,
            ends_at=start + timedelta(minutes=minutes),
            classification=classification.value,
        )
        db.add(event)
        db.commit()
        return event

    def test_a_classified_recruiter_call_can_conflict(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _book(db, workspace, john, "Amazon", BASE)
        self._external(
            db,
            john,
            "Recruiter call",
            BASE + timedelta(minutes=30),
            EventClassification.RECRUITER_CALL,
        )
        conflicts = find_conflicts(
            db, workspace, [john], start=WINDOW_START, end=WINDOW_END
        )
        assert len(conflicts) == 1

    def test_an_ordinary_meeting_does_not_conflict(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        """Otherwise every busy calendar would drown the panel in warnings."""
        _book(db, workspace, john, "Amazon", BASE)
        self._external(
            db,
            john,
            "Team standup",
            BASE + timedelta(minutes=30),
            EventClassification.NORMAL_MEETING,
        )
        assert (
            find_conflicts(db, workspace, [john], start=WINDOW_START, end=WINDOW_END)
            == []
        )

    def test_an_all_day_event_never_conflicts(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _book(db, workspace, john, "Amazon", BASE)
        event = self._external(
            db,
            john,
            "Company holiday",
            BASE.replace(hour=0),
            EventClassification.INTERVIEW,
            minutes=24 * 60,
        )
        event.is_all_day = True
        db.commit()
        assert (
            find_conflicts(db, workspace, [john], start=WINDOW_START, end=WINDOW_END)
            == []
        )


def test_no_people_selected_returns_nothing(
    db: Session, workspace: Workspace
) -> None:
    assert find_conflicts(db, workspace, [], start=WINDOW_START, end=WINDOW_END) == []
