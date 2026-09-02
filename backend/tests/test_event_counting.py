"""Every imported event counts as an interview until someone says otherwise.

The old rule was the opposite: an imported event was inert until a human filed
it as an interview, which meant a calendar full of real interviews showed
nothing anywhere. These tests pin the inversion, the two shapes that are
pre-filed out of it (repeating and all-day), and the fact that an interview
with no application behind it is still counted — and still asked about.
"""

from __future__ import annotations

import importlib.util
import pathlib
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.domains.analytics.periods import Period
from app.domains.analytics.service import compute_analytics
from app.domains.applications.service import create_application
from app.domains.calendar.providers.base import NormalizedEvent
from app.domains.calendar.service import (
    FeedFilters,
    build_feed,
    list_suggestions,
)
from app.domains.calendar.sync import _initial_classification
from app.domains.interviews.service import create_stage
from app.enums import (
    NON_INTERVIEW_CLASSIFICATIONS,
    EventClassification,
    EventStatus,
    counts_as_interview,
)
from app.models import CalendarEvent, InterviewEvent, Person, Workspace
from app.schemas.application import ApplicationCreate
from app.schemas.interview import InterviewEventCreate, InterviewStageCreate

ALL_TIME = Period("all_time", "All Time", None, None)

BASE = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)
WINDOW_START = BASE - timedelta(days=7)
WINDOW_END = BASE + timedelta(days=7)


@pytest.fixture
def john(make_person) -> Person:
    return make_person("John Carter")


def _event(
    db: Session,
    person: Person,
    title: str = "Interview with Acme",
    *,
    start: datetime = BASE,
    classification: EventClassification = EventClassification.UNCLASSIFIED,
    status: EventStatus = EventStatus.CONFIRMED,
    dismissed: bool = False,
) -> CalendarEvent:
    event = CalendarEvent(
        person_id=person.id,
        title=title,
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        classification=classification.value,
        status=status.value,
        detection_dismissed=dismissed,
    )
    db.add(event)
    db.commit()
    return event


def _feed(db: Session, workspace: Workspace, person: Person, **kwargs):
    return build_feed(
        db,
        workspace,
        [person],
        start=WINDOW_START,
        end=WINDOW_END,
        include_conflicts=False,
        **kwargs,
    )


# --------------------------------------------------------------------------
# The rule itself
# --------------------------------------------------------------------------


class TestCountingRule:
    def test_an_untouched_event_counts(self) -> None:
        assert counts_as_interview(EventClassification.UNCLASSIFIED.value)

    @pytest.mark.parametrize(
        "classification",
        [
            EventClassification.INTERVIEW,
            EventClassification.RECRUITER_CALL,
            EventClassification.ASSESSMENT,
        ],
    )
    def test_interview_kinds_count(self, classification) -> None:
        assert counts_as_interview(classification.value)

    @pytest.mark.parametrize(
        "classification",
        [
            EventClassification.PERSONAL,
            EventClassification.NORMAL_MEETING,
            EventClassification.IGNORED,
        ],
    )
    def test_the_three_opt_outs_do_not_count(self, classification) -> None:
        assert not counts_as_interview(classification.value)

    def test_the_opt_out_set_is_exactly_those_three(self) -> None:
        # Adding a classification should be a deliberate decision about which
        # side of the line it falls on, so the set is pinned.
        expected = {"personal", "normal_meeting", "ignored"}
        assert expected == NON_INTERVIEW_CLASSIFICATIONS

    def test_normal_meeting_keeps_its_stored_value(self) -> None:
        # It reads as "Not an interview" now, but the value is persisted in
        # every existing row and renaming it would need a migration.
        assert EventClassification.NORMAL_MEETING.value == "normal_meeting"


# --------------------------------------------------------------------------
# What the importer pre-files
# --------------------------------------------------------------------------


class TestInitialClassification:
    def _incoming(self, **kwargs) -> NormalizedEvent:
        defaults = dict(
            provider_event_id="evt-1",
            title="Something",
            starts_at=BASE,
            ends_at=BASE + timedelta(hours=1),
        )
        return NormalizedEvent(**{**defaults, **kwargs})

    def test_a_one_off_meeting_is_left_alone(self) -> None:
        assert (
            _initial_classification(self._incoming())
            is EventClassification.UNCLASSIFIED
        )

    def test_a_repeating_event_is_pre_filed_out(self) -> None:
        # A weekly standup would otherwise arrive fifty-two times.
        assert (
            _initial_classification(self._incoming(is_recurring=True))
            is EventClassification.NORMAL_MEETING
        )

    def test_an_all_day_block_is_pre_filed_out(self) -> None:
        assert (
            _initial_classification(self._incoming(is_all_day=True))
            is EventClassification.NORMAL_MEETING
        )


# --------------------------------------------------------------------------
# The calendar feed
# --------------------------------------------------------------------------


class TestFeed:
    def test_an_unclassified_event_is_drawn_as_an_interview(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _event(db, john)
        [block] = _feed(db, workspace, john).events
        assert block.counts_as_interview is True

    def test_a_personal_event_is_not(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _event(db, john, "Dentist", classification=EventClassification.PERSONAL)
        [block] = _feed(db, workspace, john).events
        assert block.counts_as_interview is False

    def test_a_not_an_interview_event_is_not(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _event(db, john, "Standup", classification=EventClassification.NORMAL_MEETING)
        [block] = _feed(db, workspace, john).events
        assert block.counts_as_interview is False

    def test_a_linked_interview_always_counts(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        application = create_application(
            db,
            workspace,
            ApplicationCreate(
                person_id=john.id, company_name="Acme", job_title="Engineer"
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
                        starts_at=BASE, ends_at=BASE + timedelta(hours=1)
                    )
                ],
            ),
        )
        [block] = _feed(db, workspace, john).events
        assert block.kind == "interview"
        assert block.counts_as_interview is True
        assert block.needs_application is False

    def test_an_unconnected_interview_asks_to_be_connected(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _event(db, john)
        [block] = _feed(db, workspace, john).events
        assert block.needs_application is True

    def test_a_personal_event_is_never_asked_about(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _event(db, john, "Dentist", classification=EventClassification.PERSONAL)
        [block] = _feed(db, workspace, john).events
        assert block.needs_application is False

    def test_interviews_only_hides_the_three_opt_outs(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _event(db, john, "Screen")  # unclassified — counts
        _event(db, john, "Dentist", classification=EventClassification.PERSONAL)
        _event(db, john, "Standup", classification=EventClassification.NORMAL_MEETING)
        _event(db, john, "Noise", classification=EventClassification.IGNORED)

        feed = _feed(
            db, workspace, john, filters=FeedFilters(show_non_interview=False)
        )
        assert [e.title for e in feed.events] == ["Screen"]

    def test_showing_everything_still_hides_ignored(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _event(db, john, "Screen")
        _event(db, john, "Noise", classification=EventClassification.IGNORED)
        feed = _feed(db, workspace, john, filters=FeedFilters(show_non_interview=True))
        assert [e.title for e in feed.events] == ["Screen"]


# --------------------------------------------------------------------------
# "Connect this to an application"
# --------------------------------------------------------------------------


class TestConnectQueue:
    def test_a_low_scoring_event_is_still_asked_about(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        # The old rule needed a detection score of 0.5 to ask. A plainly-titled
        # interview scores nothing and was silently dropped.
        event = _event(db, john, "Chat with Dana", start=BASE + timedelta(days=1))
        assert event.detection_score == 0.0
        [suggestion] = list_suggestions(db, workspace, [john.id])
        assert suggestion.event_id == event.id

    def test_an_event_that_already_happened_is_still_asked_about(
        self, db: Session, workspace: Workspace, john: Person, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "app.domains.calendar.service.utcnow", lambda: BASE + timedelta(days=2)
        )
        _event(db, john, "Tuesday's interview")
        assert len(list_suggestions(db, workspace, [john.id])) == 1

    def test_an_old_event_falls_off_the_list(
        self, db: Session, workspace: Workspace, john: Person, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "app.domains.calendar.service.utcnow", lambda: BASE + timedelta(days=60)
        )
        _event(db, john, "Ancient history")
        assert list_suggestions(db, workspace, [john.id]) == []

    def test_a_personal_event_is_not_asked_about(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _event(db, john, "Dentist", classification=EventClassification.PERSONAL)
        assert list_suggestions(db, workspace, [john.id]) == []

    def test_a_cancelled_event_is_not_asked_about(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _event(db, john, "Called off", status=EventStatus.CANCELLED)
        assert list_suggestions(db, workspace, [john.id]) == []

    def test_dismissing_stops_the_asking(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _event(db, john, "Not tracking this one", dismissed=True)
        assert list_suggestions(db, workspace, [john.id]) == []

    def test_a_connected_event_is_not_asked_about(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        application = create_application(
            db,
            workspace,
            ApplicationCreate(
                person_id=john.id, company_name="Acme", job_title="Engineer"
            ),
        )
        stage = create_stage(
            db,
            workspace,
            application.id,
            InterviewStageCreate(
                type_key="technical",
                events=[
                    InterviewEventCreate(
                        starts_at=BASE, ends_at=BASE + timedelta(hours=1)
                    )
                ],
            ),
        )
        event = _event(db, john)
        link = db.query(InterviewEvent).filter_by(interview_stage_id=stage.id).one()
        link.calendar_event_id = event.id
        db.commit()

        assert list_suggestions(db, workspace, [john.id]) == []


# --------------------------------------------------------------------------
# The dashboard
# --------------------------------------------------------------------------


class TestDashboard:
    def _volume(self, db: Session, workspace: Workspace, john: Person):
        return compute_analytics(
            db,
            workspace,
            [john],
            ALL_TIME,
            include_comparison=False,
            include_trend=False,
        ).volume

    def test_calendar_interviews_are_counted(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _event(db, john, "Screen")
        _event(db, john, "Onsite", start=BASE + timedelta(days=1))
        volume = self._volume(db, workspace, john)
        assert volume.calendar_interviews == 2

    def test_opted_out_events_are_not_counted(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _event(db, john, "Screen")
        _event(db, john, "Dentist", classification=EventClassification.PERSONAL)
        _event(db, john, "Standup", classification=EventClassification.NORMAL_MEETING)
        _event(db, john, "Noise", classification=EventClassification.IGNORED)
        assert self._volume(db, workspace, john).calendar_interviews == 1

    def test_a_cancelled_event_is_not_counted(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        _event(db, john, "Called off", status=EventStatus.CANCELLED)
        assert self._volume(db, workspace, john).calendar_interviews == 0

    def test_unconnected_interviews_are_reported_separately(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        # This is the number that explains why the funnel is lower than the
        # calendar: these interviews feed no application, so no rate sees them.
        application = create_application(
            db,
            workspace,
            ApplicationCreate(
                person_id=john.id, company_name="Acme", job_title="Engineer"
            ),
        )
        stage = create_stage(
            db,
            workspace,
            application.id,
            InterviewStageCreate(
                type_key="technical",
                events=[
                    InterviewEventCreate(
                        starts_at=BASE, ends_at=BASE + timedelta(hours=1)
                    )
                ],
            ),
        )
        connected = _event(db, john, "Connected")
        link = db.query(InterviewEvent).filter_by(interview_stage_id=stage.id).one()
        link.calendar_event_id = connected.id
        db.commit()

        _event(db, john, "Floating", start=BASE + timedelta(days=1))

        volume = self._volume(db, workspace, john)
        assert volume.calendar_interviews == 2
        assert volume.calendar_interviews_unlinked == 1

    def test_no_calendar_means_zero_not_an_error(
        self, db: Session, workspace: Workspace, john: Person
    ) -> None:
        volume = self._volume(db, workspace, john)
        assert volume.calendar_interviews == 0
        assert volume.calendar_interviews_unlinked == 0


# --------------------------------------------------------------------------
# Bringing existing rows across
# --------------------------------------------------------------------------


def _load_migration():
    """The recurrence migration, loaded by path.

    `alembic/versions` is not a package: migration files are frozen snapshots
    rather than importable modules. Loading it directly is the only way to test
    the data step without shelling out to alembic.
    """
    path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "f4a1b8c7d203_event_recurrence.py"
    )
    spec = importlib.util.spec_from_file_location("_recurrence_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestBackfill:
    """The migration's data step, run against a live session.

    Events imported under the old rule are sitting in every existing database
    as `unclassified`, which used to mean "not judged yet" and now means "this
    is an interview". The repeating ones have to be moved or the first thing
    the change does is invent a year of standups.
    """

    def _run(self, db: Session) -> None:
        # Migrations are deliberately not importable as a package — they are
        # frozen snapshots, not app code — so it is loaded by path.
        _backfill = _load_migration()._backfill

        db.commit()
        with patch("alembic.op.get_bind", return_value=db.connection()):
            _backfill()
        db.commit()

    def _imported(
        self,
        db: Session,
        person: Person,
        title: str,
        *,
        raw: dict | None = None,
        is_all_day: bool = False,
        classification: EventClassification = EventClassification.UNCLASSIFIED,
        locked: bool = False,
    ) -> CalendarEvent:
        event = CalendarEvent(
            person_id=person.id,
            title=title,
            starts_at=BASE,
            ends_at=BASE + timedelta(hours=1),
            classification=classification.value,
            classification_locked=locked,
            is_all_day=is_all_day,
            raw=raw,
        )
        db.add(event)
        db.commit()
        return event

    def test_a_google_series_is_recognised(self, db: Session, john: Person) -> None:
        event = self._imported(
            db, john, "Standup", raw={"recurringEventId": "abc123"}
        )
        self._run(db)
        db.refresh(event)
        assert event.is_recurring is True
        assert event.classification == EventClassification.NORMAL_MEETING.value

    def test_a_microsoft_series_is_recognised(self, db: Session, john: Person) -> None:
        event = self._imported(
            db, john, "Standup", raw={"type": "occurrence", "seriesMasterId": "s1"}
        )
        self._run(db)
        db.refresh(event)
        assert event.is_recurring is True

    def test_an_all_day_block_is_moved(self, db: Session, john: Person) -> None:
        event = self._imported(db, john, "PTO", is_all_day=True)
        self._run(db)
        db.refresh(event)
        assert event.classification == EventClassification.NORMAL_MEETING.value

    def test_a_one_off_meeting_is_left_counting(
        self, db: Session, john: Person
    ) -> None:
        event = self._imported(db, john, "Interview with Acme", raw={"id": "x"})
        self._run(db)
        db.refresh(event)
        assert event.is_recurring is False
        assert event.classification == EventClassification.UNCLASSIFIED.value

    def test_a_hand_made_decision_is_never_overwritten(
        self, db: Session, john: Person
    ) -> None:
        # Someone deliberately called this recurring event an interview. A
        # migration has no business disagreeing.
        event = self._imported(
            db,
            john,
            "Weekly with the hiring manager",
            raw={"recurringEventId": "abc"},
            classification=EventClassification.INTERVIEW,
            locked=True,
        )
        self._run(db)
        db.refresh(event)
        assert event.classification == EventClassification.INTERVIEW.value

    def test_a_missing_payload_is_not_an_error(
        self, db: Session, john: Person
    ) -> None:
        event = self._imported(db, john, "No payload", raw=None)
        self._run(db)
        db.refresh(event)
        assert event.is_recurring is False
