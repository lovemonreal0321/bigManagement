"""Calendar sync tests: provider mapping, deduplication, provider-wins timing.

A fake adapter stands in for Google/Microsoft so the sync engine is tested
without network access or credentials (spec §57, §69).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest
from sqlalchemy.orm import Session

from app.domains.calendar import sync as sync_service
from app.domains.calendar.providers.base import (
    CalendarProviderAdapter,
    EventPage,
    NormalizedEvent,
    ProviderCalendar,
    extract_meeting_url,
)
from app.domains.calendar.providers.google import _normalise_event as google_normalise
from app.domains.calendar.providers.microsoft import (
    _normalise_event as graph_normalise,
)
from app.enums import (
    CalendarProvider,
    ConnectionStatus,
    EventStatus,
    InterviewOutcome,
    InterviewStatus,
)
from app.models import (
    CalendarConnection,
    CalendarEvent,
    ExternalCalendar,
    InterviewEvent,
    Person,
    Workspace,
)

BASE = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# Provider payload mapping
# --------------------------------------------------------------------------


class TestGoogleMapping:
    def test_timed_event(self) -> None:
        event = google_normalise(
            {
                "id": "evt-1",
                "iCalUID": "uid-1@google.com",
                "etag": '"123"',
                "summary": "Amazon — Technical Interview",
                "description": "Coding round",
                "location": "https://zoom.us/j/999",
                "status": "confirmed",
                "organizer": {"email": "recruiter@amazon.com", "displayName": "Ana"},
                "attendees": [
                    {"email": "john@example.com", "responseStatus": "accepted"}
                ],
                "start": {
                    "dateTime": "2026-08-20T10:00:00-04:00",
                    "timeZone": "America/New_York",
                },
                "end": {
                    "dateTime": "2026-08-20T11:00:00-04:00",
                    "timeZone": "America/New_York",
                },
            }
        )
        assert event is not None
        assert event.starts_at == BASE
        assert event.ends_at == BASE + timedelta(hours=1)
        # The provider's original zone is preserved (spec §44).
        assert event.start_timezone == "America/New_York"
        assert event.organizer_email == "recruiter@amazon.com"
        assert event.meeting_url == "https://zoom.us/j/999"
        assert event.status is EventStatus.CONFIRMED

    def test_all_day_event(self) -> None:
        event = google_normalise(
            {
                "id": "evt-2",
                "summary": "Company holiday",
                "start": {"date": "2026-08-20"},
                "end": {"date": "2026-08-21"},
            }
        )
        assert event is not None
        assert event.is_all_day is True

    def test_missing_end_defaults_to_one_hour(self) -> None:
        event = google_normalise(
            {"id": "e", "summary": "x", "start": {"dateTime": "2026-08-20T14:00:00Z"}}
        )
        assert event is not None
        assert event.ends_at - event.starts_at == timedelta(hours=1)

    def test_event_without_a_start_is_skipped(self) -> None:
        assert google_normalise({"id": "e", "summary": "x"}) is None

    def test_hangout_link_is_used_as_the_meeting_url(self) -> None:
        event = google_normalise(
            {
                "id": "e",
                "summary": "x",
                "hangoutLink": "https://meet.google.com/abc-defg-hij",
                "start": {"dateTime": "2026-08-20T14:00:00Z"},
                "end": {"dateTime": "2026-08-20T15:00:00Z"},
            }
        )
        assert event is not None
        assert event.meeting_url == "https://meet.google.com/abc-defg-hij"


class TestMicrosoftMapping:
    def test_timed_event(self) -> None:
        event = graph_normalise(
            {
                "id": "graph-1",
                "iCalUId": "uid-graph-1",
                "@odata.etag": 'W/"abc"',
                "subject": "Microsoft — Hiring Manager",
                "bodyPreview": "Chat with the hiring manager",
                "isAllDay": False,
                "start": {"dateTime": "2026-08-20T14:00:00.0000000", "timeZone": "UTC"},
                "end": {"dateTime": "2026-08-20T15:00:00.0000000", "timeZone": "UTC"},
                "organizer": {
                    "emailAddress": {"address": "hm@microsoft.com", "name": "Dana"}
                },
                "onlineMeeting": {"joinUrl": "https://teams.microsoft.com/l/xyz"},
                "attendees": [
                    {
                        "emailAddress": {"address": "david@example.com"},
                        "status": {"response": "accepted"},
                    }
                ],
            }
        )
        assert event is not None
        assert event.starts_at == BASE
        assert event.meeting_url == "https://teams.microsoft.com/l/xyz"
        assert event.organizer_email == "hm@microsoft.com"
        assert event.attendees[0]["email"] == "david@example.com"

    def test_windows_timezone_is_mapped_to_iana(self) -> None:
        event = graph_normalise(
            {
                "id": "g",
                "subject": "x",
                "start": {
                    "dateTime": "2026-08-20T10:00:00.0000000",
                    "timeZone": "Eastern Standard Time",
                },
                "end": {
                    "dateTime": "2026-08-20T11:00:00.0000000",
                    "timeZone": "Eastern Standard Time",
                },
            }
        )
        assert event is not None
        assert event.start_timezone == "America/New_York"
        assert event.starts_at == BASE


class TestMeetingUrlExtraction:
    @pytest.mark.parametrize(
        "text",
        [
            "Join at https://zoom.us/j/12345",
            "https://meet.google.com/abc-defg-hij is the link",
            "Dial in: https://teams.microsoft.com/l/meetup-join/xyz",
        ],
    )
    def test_finds_known_platforms(self, text: str) -> None:
        assert extract_meeting_url(text) is not None

    def test_ignores_unrelated_links(self) -> None:
        assert extract_meeting_url("See https://example.com/jobs/123") is None

    def test_strips_trailing_punctuation(self) -> None:
        url = extract_meeting_url("Join https://zoom.us/j/12345.")
        assert url == "https://zoom.us/j/12345"


# --------------------------------------------------------------------------
# Sync engine
# --------------------------------------------------------------------------


class FakeAdapter(CalendarProviderAdapter):
    """Stands in for a real provider. Returns whatever the test queues up."""

    key = CalendarProvider.GOOGLE.value
    display_name = "Fake Calendar"
    scopes: ClassVar[list[str]] = []

    def __init__(
        self, pages: list[EventPage] | dict[str, list[EventPage]]
    ) -> None:
        #: Either one sequence of pages shared by every calendar, or a
        #: per-calendar sequence keyed by provider calendar id.
        self.pages = pages
        self.calls = 0
        self.calls_per_calendar: dict[str, int] = {}

    @property
    def is_configured(self) -> bool:
        return True

    def missing_settings(self) -> list[str]:
        return []

    def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        return "https://example.com/auth"

    def exchange_code(self, *, code: str, redirect_uri: str):  # pragma: no cover
        raise NotImplementedError

    def refresh_tokens(self, refresh_token: str):  # pragma: no cover
        raise NotImplementedError

    def list_calendars(self, access_token: str) -> list[ProviderCalendar]:
        return [ProviderCalendar(id="primary", name="Primary", is_primary=True)]

    def list_events(self, access_token, *, calendar_id, start, end, sync_token=None):
        self.calls += 1
        if isinstance(self.pages, dict):
            pages = self.pages.get(calendar_id, [EventPage()])
            index = self.calls_per_calendar.get(calendar_id, 0)
            self.calls_per_calendar[calendar_id] = index + 1
            return pages[min(index, len(pages) - 1)]
        return self.pages[min(self.calls - 1, len(self.pages) - 1)]

    def create_event(self, access_token, *, calendar_id, draft):  # pragma: no cover
        raise NotImplementedError

    def update_event(
        self, access_token, *, calendar_id, provider_event_id, draft
    ):  # pragma: no cover
        raise NotImplementedError

    def delete_event(
        self, access_token, *, calendar_id, provider_event_id
    ):  # pragma: no cover
        raise NotImplementedError


def _event(
    provider_id: str,
    *,
    title: str = "Amazon — Technical Interview",
    start: datetime = BASE,
    minutes: int = 60,
    ical_uid: str | None = None,
) -> NormalizedEvent:
    return NormalizedEvent(
        provider_event_id=provider_id,
        title=title,
        starts_at=start,
        ends_at=start + timedelta(minutes=minutes),
        ical_uid=ical_uid or f"{provider_id}@example.com",
        start_timezone="America/New_York",
    )


@pytest.fixture
def connection(db: Session, workspace: Workspace, make_person) -> CalendarConnection:
    person: Person = make_person("John Carter")
    conn = CalendarConnection(
        person_id=person.id,
        provider=CalendarProvider.GOOGLE.value,
        provider_account_id="acct-1",
        account_email="john@example.com",
        access_token="token",
        refresh_token="refresh",
        # Comfortably in the future so no refresh is attempted.
        token_expires_at=datetime.now(UTC) + timedelta(days=1),
        status=ConnectionStatus.CONNECTED.value,
    )
    db.add(conn)
    db.flush()
    db.add(
        ExternalCalendar(
            connection_id=conn.id,
            provider_calendar_id="primary",
            name="Primary",
            is_primary=True,
            is_selected=True,
        )
    )
    db.commit()
    return conn


def _install(monkeypatch: pytest.MonkeyPatch, adapter: FakeAdapter) -> None:
    monkeypatch.setattr(sync_service, "get_adapter", lambda provider: adapter)


class TestSyncImport:
    def test_imports_events(
        self, db, workspace, connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, FakeAdapter([EventPage(events=[_event("a"), _event("b")])]))
        result = sync_service.sync_connection(db, workspace, connection)

        assert result.error is None
        assert result.events_created == 2
        assert db.query(CalendarEvent).count() == 2

    def test_rerunning_updates_rather_than_duplicating(
        self, db, workspace, connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Idempotency: the unique (calendar, provider_event_id) index."""
        adapter = FakeAdapter([EventPage(events=[_event("a")])])
        _install(monkeypatch, adapter)

        sync_service.sync_connection(db, workspace, connection)
        second = sync_service.sync_connection(db, workspace, connection)

        assert second.events_created == 0
        assert second.events_updated == 1
        assert db.query(CalendarEvent).count() == 1

    def test_detection_runs_but_never_classifies(
        self, db, workspace, connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Spec §8: heuristics may suggest, never decide."""
        _install(monkeypatch, FakeAdapter([EventPage(events=[_event("a")])]))
        sync_service.sync_connection(db, workspace, connection)

        event = db.query(CalendarEvent).one()
        assert event.detection_score > 0.5
        assert event.classification == "unclassified"

    def test_a_human_classification_survives_the_next_sync(
        self, db, workspace, connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, FakeAdapter([EventPage(events=[_event("a")])]))
        sync_service.sync_connection(db, workspace, connection)

        event = db.query(CalendarEvent).one()
        event.classification = "personal"
        event.classification_locked = True
        db.commit()

        sync_service.sync_connection(db, workspace, connection)
        db.refresh(event)
        assert event.classification == "personal"

    def test_cancelled_events_are_soft_deleted(
        self, db, workspace, connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter = FakeAdapter(
            [
                EventPage(events=[_event("a")]),
                EventPage(deleted_event_ids=["a"]),
            ]
        )
        _install(monkeypatch, adapter)

        sync_service.sync_connection(db, workspace, connection)
        result = sync_service.sync_connection(db, workspace, connection)

        assert result.events_deleted == 1
        event = db.query(CalendarEvent).one()
        assert event.deleted_at is not None


class TestDeduplication:
    def _add_second_calendar(self, db: Session, connection: CalendarConnection) -> None:
        db.add(
            ExternalCalendar(
                connection_id=connection.id,
                provider_calendar_id="secondary",
                name="Secondary",
                is_selected=True,
            )
        )
        db.commit()

    def test_the_same_meeting_in_two_calendars_is_imported_once(
        self, db, workspace, connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Spec §7: one meeting invited to two connected calendars arrives with
        two provider ids but one iCalUID, and must not be stored twice."""
        self._add_second_calendar(db, connection)

        _install(
            monkeypatch,
            FakeAdapter(
                {
                    "primary": [
                        EventPage(
                            events=[_event("evt-a", ical_uid="shared@example.com")]
                        )
                    ],
                    "secondary": [
                        EventPage(
                            events=[_event("evt-b", ical_uid="shared@example.com")]
                        )
                    ],
                }
            ),
        )

        result = sync_service.sync_connection(db, workspace, connection)

        assert result.duplicates_skipped == 1
        assert result.events_created == 1
        assert (
            db.query(CalendarEvent)
            .filter(CalendarEvent.ical_uid == "shared@example.com")
            .count()
            == 1
        )

    def test_a_recurring_series_in_one_calendar_is_not_collapsed(
        self, db, workspace, connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Google gives every instance of a recurring series the same iCalUID
        when `singleEvents=true`. Deduplicating on the UID alone would delete a
        whole weekly series down to one event.
        """
        weekly = [
            _event(
                f"instance-{i}",
                start=BASE + timedelta(days=7 * i),
                ical_uid="weekly@example.com",
            )
            for i in range(4)
        ]
        _install(monkeypatch, FakeAdapter([EventPage(events=weekly)]))

        result = sync_service.sync_connection(db, workspace, connection)

        assert result.duplicates_skipped == 0
        assert db.query(CalendarEvent).count() == 4

    def test_a_recurring_series_in_two_calendars_dedupes_per_instance(
        self, db, workspace, connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._add_second_calendar(db, connection)
        series = lambda prefix: [  # noqa: E731 - compact test helper
            _event(
                f"{prefix}-{i}",
                start=BASE + timedelta(days=7 * i),
                ical_uid="weekly@example.com",
            )
            for i in range(3)
        ]
        _install(
            monkeypatch,
            FakeAdapter(
                {
                    "primary": [EventPage(events=series("a"))],
                    "secondary": [EventPage(events=series("b"))],
                }
            ),
        )

        result = sync_service.sync_connection(db, workspace, connection)

        assert result.events_created == 3
        assert result.duplicates_skipped == 3
        assert db.query(CalendarEvent).count() == 3


class TestProviderWinsOnTiming:
    """The behaviour the user chose: the calendar is the source of truth."""

    def _link_interview(
        self, db: Session, workspace: Workspace, connection: CalendarConnection
    ):
        from app.domains.applications.service import create_application
        from app.domains.interviews.service import create_stage
        from app.schemas.application import ApplicationCreate
        from app.schemas.interview import InterviewEventCreate, InterviewStageCreate

        application = create_application(
            db,
            workspace,
            ApplicationCreate(
                person_id=connection.person_id,
                company_name="Amazon",
                job_title="Engineer",
            ),
        )
        stage = create_stage(
            db,
            workspace,
            application.id,
            InterviewStageCreate(
                type_key="technical",
                events=[
                    InterviewEventCreate(starts_at=BASE, ends_at=BASE + timedelta(hours=1))
                ],
            ),
        )
        calendar_event = db.query(CalendarEvent).one()
        interview_event = db.query(InterviewEvent).one()
        interview_event.calendar_event_id = calendar_event.id
        db.commit()
        return stage, interview_event

    def test_a_provider_reschedule_moves_the_interview(
        self, db, workspace, connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        moved = BASE + timedelta(days=2)
        adapter = FakeAdapter(
            [
                EventPage(events=[_event("a")]),
                EventPage(events=[_event("a", start=moved)]),
            ]
        )
        _install(monkeypatch, adapter)

        sync_service.sync_connection(db, workspace, connection)
        stage, interview_event = self._link_interview(db, workspace, connection)

        result = sync_service.sync_connection(db, workspace, connection)

        db.refresh(interview_event)
        db.refresh(stage)
        assert result.interviews_rescheduled == 1
        assert interview_event.starts_at == moved
        assert stage.scheduled_start == moved

    def test_a_provider_cancellation_cancels_the_interview(
        self, db, workspace, connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter = FakeAdapter(
            [
                EventPage(events=[_event("a")]),
                EventPage(deleted_event_ids=["a"]),
            ]
        )
        _install(monkeypatch, adapter)

        sync_service.sync_connection(db, workspace, connection)
        stage, _ = self._link_interview(db, workspace, connection)

        result = sync_service.sync_connection(db, workspace, connection)

        db.refresh(stage)
        assert result.interviews_cancelled == 1
        assert stage.status == InterviewStatus.CANCELLED.value
        assert stage.outcome == InterviewOutcome.CANCELLED.value

    def test_a_completed_interview_is_not_retroactively_cancelled(
        self, db, workspace, connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deleting a past event from the calendar must not erase the fact that
        the interview happened."""
        adapter = FakeAdapter(
            [
                EventPage(events=[_event("a")]),
                EventPage(deleted_event_ids=["a"]),
            ]
        )
        _install(monkeypatch, adapter)

        sync_service.sync_connection(db, workspace, connection)
        stage, _ = self._link_interview(db, workspace, connection)
        stage.status = InterviewStatus.COMPLETED.value
        stage.outcome = InterviewOutcome.PASSED.value
        db.commit()

        sync_service.sync_connection(db, workspace, connection)

        db.refresh(stage)
        assert stage.status == InterviewStatus.COMPLETED.value
        assert stage.outcome == InterviewOutcome.PASSED.value


class TestErrorHandling:
    def test_an_unconfigured_provider_reports_instead_of_raising(
        self, db, workspace, connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter = FakeAdapter([EventPage()])
        monkeypatch.setattr(
            type(adapter), "is_configured", property(lambda self: False)
        )
        _install(monkeypatch, adapter)

        result = sync_service.sync_connection(db, workspace, connection)
        assert result.error is not None
        assert "not configured" in result.error

    def test_a_missing_refresh_token_marks_the_connection_expired(
        self, db, workspace, connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection.refresh_token = None
        connection.token_expires_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()
        _install(monkeypatch, FakeAdapter([EventPage()]))

        result = sync_service.sync_connection(db, workspace, connection)

        db.refresh(connection)
        assert connection.status == ConnectionStatus.EXPIRED.value
        assert result.error is not None
