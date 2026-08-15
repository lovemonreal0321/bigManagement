"""Two-way calendar write-back (spec §48).

The safety rule: **this app only ever writes events it created.** An event that
came from the user's own calendar is never overwritten, moved or deleted by the
app — `InterviewEvent.source` decides, and anything marked
`external_provider` is left strictly alone.

Failures here are recorded on the row, not raised. Losing a manually entered
interview because Google was briefly unreachable would be much worse than
showing a "couldn't sync" badge next to it.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.timeutils import utcnow
from app.domains.calendar.providers import get_adapter
from app.domains.calendar.providers.base import EventDraft
from app.domains.calendar.sync import ensure_access_token
from app.enums import ConnectionStatus, EventSource, SyncState
from app.models import (
    Application,
    CalendarConnection,
    CalendarEvent,
    ExternalCalendar,
    InterviewEvent,
    InterviewStage,
    Person,
    Workspace,
)

logger = logging.getLogger(__name__)


def find_writable_calendar(
    db: Session, person_id: str
) -> tuple[CalendarConnection, ExternalCalendar] | None:
    """The calendar app-created events go to: the person's primary writable
    calendar on a healthy connection."""
    rows = db.execute(
        select(CalendarConnection, ExternalCalendar)
        .join(ExternalCalendar, ExternalCalendar.connection_id == CalendarConnection.id)
        .where(
            CalendarConnection.person_id == person_id,
            CalendarConnection.status == ConnectionStatus.CONNECTED.value,
            ExternalCalendar.is_selected.is_(True),
            ExternalCalendar.can_write.is_(True),
        )
        .order_by(ExternalCalendar.is_primary.desc())
    ).all()
    if not rows:
        return None
    connection, calendar = rows[0]
    return connection, calendar


def _build_draft(
    stage: InterviewStage, event: InterviewEvent, application: Application, person: Person
) -> EventDraft:
    description_lines = [
        f"{application.job_title} at {application.company_name}",
        f"Stage: {stage.name}",
    ]
    if event.interviewer_names:
        description_lines.append(f"Interviewer(s): {event.interviewer_names}")
    if application.job_url:
        description_lines.append(f"Job posting: {application.job_url}")
    description_lines.append("")
    description_lines.append("Added by Job Search Command Center.")

    return EventDraft(
        title=f"{application.company_name} — {event.title}",
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        description="\n".join(description_lines),
        location=event.meeting_url or event.location,
        timezone=event.timezone or person.timezone,
    )


def push_event(
    db: Session, workspace: Workspace, stage: InterviewStage, event: InterviewEvent
) -> bool:
    """Create or update this interview slot on the person's calendar.

    Returns True on success. On failure the reason is stored on the row and
    False is returned — the caller's transaction continues either way.
    """
    if event.source == EventSource.EXTERNAL_PROVIDER.value:
        # The user's own event; the app does not get to rewrite it.
        event.sync_error = (
            "This event came from the calendar, so it is not overwritten here. "
            "Edit it in the calendar instead."
        )
        return False

    application = db.get(Application, stage.application_id)
    if application is None:  # pragma: no cover
        return False
    person = db.get(Person, application.person_id)
    if person is None:  # pragma: no cover
        return False

    target = find_writable_calendar(db, person.id)
    if target is None:
        event.sync_state = SyncState.LOCAL_ONLY.value
        event.sync_error = (
            f"No writable calendar is connected for {person.display_name}. "
            "Connect one in Settings to sync interviews out."
        )
        return False

    connection, calendar = target
    adapter = get_adapter(connection.provider)
    draft = _build_draft(stage, event, application, person)

    try:
        access_token = ensure_access_token(db, connection)
        existing = (
            db.get(CalendarEvent, event.calendar_event_id)
            if event.calendar_event_id
            else None
        )

        if existing is not None and existing.provider_event_id and existing.is_app_created:
            normalised = adapter.update_event(
                access_token,
                calendar_id=calendar.provider_calendar_id,
                provider_event_id=existing.provider_event_id,
                draft=draft,
            )
            calendar_event = existing
        else:
            normalised = adapter.create_event(
                access_token, calendar_id=calendar.provider_calendar_id, draft=draft
            )
            calendar_event = CalendarEvent(
                person_id=person.id,
                external_calendar_id=calendar.id,
                connection_id=connection.id,
                provider=connection.provider,
                source=EventSource.APP_CREATED.value,
            )
            db.add(calendar_event)

        calendar_event.provider_event_id = normalised.provider_event_id
        calendar_event.ical_uid = normalised.ical_uid
        calendar_event.etag = normalised.etag
        calendar_event.title = normalised.title[:1024]
        calendar_event.description = normalised.description
        calendar_event.location = normalised.location
        calendar_event.meeting_url = normalised.meeting_url or event.meeting_url
        calendar_event.starts_at = normalised.starts_at
        calendar_event.ends_at = normalised.ends_at
        calendar_event.start_timezone = normalised.start_timezone
        calendar_event.end_timezone = normalised.end_timezone
        calendar_event.status = normalised.status.value
        # An event this app created is known to be an interview — no detection
        # guesswork required.
        calendar_event.classification = "interview"
        calendar_event.classification_locked = True
        calendar_event.last_synced_at = utcnow()
        calendar_event.raw = normalised.raw
        db.flush()

        event.calendar_event_id = calendar_event.id
        event.sync_state = SyncState.SYNCED.value
        event.sync_error = None
        return True

    except AppError as exc:
        logger.warning("calendar write-back failed: %s", exc.message)
        event.sync_state = SyncState.FAILED.value
        event.sync_error = exc.message
        return False
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("unexpected calendar write-back failure", exc_info=exc)
        event.sync_state = SyncState.FAILED.value
        event.sync_error = "Could not add this to the calendar. You can retry from the interview."
        return False


def remove_event(db: Session, workspace: Workspace, event: InterviewEvent) -> bool:
    """Delete an app-created event from the provider. External events are left."""
    if event.source == EventSource.EXTERNAL_PROVIDER.value or not event.calendar_event_id:
        return False
    calendar_event = db.get(CalendarEvent, event.calendar_event_id)
    if (
        calendar_event is None
        or not calendar_event.is_app_created
        or not calendar_event.provider_event_id
        or not calendar_event.connection_id
        or not calendar_event.external_calendar_id
    ):
        return False

    connection = db.get(CalendarConnection, calendar_event.connection_id)
    calendar = db.get(ExternalCalendar, calendar_event.external_calendar_id)
    if connection is None or calendar is None:
        return False

    try:
        access_token = ensure_access_token(db, connection)
        get_adapter(connection.provider).delete_event(
            access_token,
            calendar_id=calendar.provider_calendar_id,
            provider_event_id=calendar_event.provider_event_id,
        )
        calendar_event.deleted_at = utcnow()
        return True
    except AppError as exc:
        logger.warning("calendar delete failed: %s", exc.message)
        event.sync_error = exc.message
        return False
