"""Calendar synchronisation engine (spec §7).

The contract the user chose: **the provider wins on timing.** When a synced
event moves, the interview linked to it moves with it. When the provider
cancels an event, the interview is marked cancelled. Interviews the app
created are pushed outward instead (see `writeback.py`), so the calendar always
holds the full picture.

Idempotency comes from the `(external_calendar_id, provider_event_id)` unique
index — re-running a sync updates rows rather than duplicating them.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import (
    AppError,
    CalendarConnectionExpiredError,
    CalendarSyncError,
    NotFoundError,
)
from app.core.timeutils import utcnow
from app.domains.activity import service as activity_service
from app.domains.calendar import detection
from app.domains.calendar.providers import get_adapter
from app.domains.calendar.providers.base import NormalizedEvent
from app.enums import (
    ActivityType,
    ConnectionStatus,
    EventClassification,
    EventSource,
    EventStatus,
    InterviewOutcome,
    InterviewStatus,
)
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
from app.schemas.calendar import SyncResultOut, SyncSummaryOut

logger = logging.getLogger(__name__)

#: Refresh a token this long before it actually expires, so a long sync does
#: not die halfway through.
TOKEN_REFRESH_MARGIN = timedelta(minutes=5)


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------


def ensure_access_token(db: Session, connection: CalendarConnection) -> str:
    """Return a usable access token, refreshing it first if needed."""
    adapter = get_adapter(connection.provider)

    fresh_enough = (
        connection.access_token
        and connection.token_expires_at is not None
        and connection.token_expires_at - TOKEN_REFRESH_MARGIN > utcnow()
    )
    if fresh_enough:
        return connection.access_token  # type: ignore[return-value]

    if not connection.refresh_token:
        # No way to renew — the user has to reconnect.
        connection.status = ConnectionStatus.EXPIRED.value
        db.commit()
        raise CalendarConnectionExpiredError(
            f"The {adapter.display_name} connection for this person expired. "
            "Please reconnect the account."
        )

    try:
        tokens = adapter.refresh_tokens(connection.refresh_token)
    except CalendarConnectionExpiredError:
        connection.status = ConnectionStatus.EXPIRED.value
        db.commit()
        raise

    connection.access_token = tokens.access_token
    connection.refresh_token = tokens.refresh_token or connection.refresh_token
    connection.token_expires_at = tokens.expires_at
    if tokens.scope:
        connection.scope = tokens.scope
    connection.status = ConnectionStatus.CONNECTED.value
    db.commit()
    return connection.access_token


# --------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------


def sync_connection(
    db: Session,
    workspace: Workspace,
    connection: CalendarConnection,
    *,
    full: bool = False,
) -> SyncResultOut:
    """Sync every selected calendar on one connection."""
    started = utcnow()
    result = SyncResultOut(
        connection_id=connection.id,
        provider=connection.provider,
        started_at=started,
        finished_at=started,
    )

    adapter = get_adapter(connection.provider)
    if not adapter.is_configured:
        result.error = (
            f"{adapter.display_name} is not configured on the server."
        )
        result.finished_at = utcnow()
        return result

    try:
        access_token = ensure_access_token(db, connection)
    except AppError as exc:
        _record_failure(db, connection, exc.message)
        result.error = exc.message
        result.finished_at = utcnow()
        return result

    past_days = connection.sync_window_past_days or workspace.sync_window_past_days
    future_days = connection.sync_window_future_days or workspace.sync_window_future_days
    window_start = utcnow() - timedelta(days=past_days)
    window_end = utcnow() + timedelta(days=future_days)

    calendars = list(
        db.scalars(
            select(ExternalCalendar).where(
                ExternalCalendar.connection_id == connection.id,
                ExternalCalendar.is_selected.is_(True),
            )
        )
    )

    for calendar in calendars:
        try:
            _sync_calendar(
                db,
                workspace,
                connection,
                calendar,
                adapter=adapter,
                access_token=access_token,
                start=window_start,
                end=window_end,
                result=result,
                full=full,
            )
            result.calendars_synced += 1
        except CalendarSyncError as exc:
            if exc.code == "sync_token_expired":
                # The cursor went stale; drop it and re-import the window once.
                logger.info("sync token expired for calendar %s, retrying full", calendar.id)
                calendar.sync_token = None
                db.commit()
                try:
                    _sync_calendar(
                        db,
                        workspace,
                        connection,
                        calendar,
                        adapter=adapter,
                        access_token=access_token,
                        start=window_start,
                        end=window_end,
                        result=result,
                        full=True,
                    )
                    result.calendars_synced += 1
                    continue
                except AppError as retry_exc:
                    result.error = retry_exc.message
            else:
                result.error = exc.message
        except AppError as exc:
            result.error = exc.message
        except Exception:
            # A provider can return anything. An unexpected shape used to
            # escape all the way out and 500 the whole request, which also
            # stripped the CORS headers and made it look like a CORS fault in
            # the browser. One calendar failing is a per-calendar problem.
            logger.exception(
                "unexpected error syncing calendar %s on connection %s",
                calendar.id,
                connection.id,
            )
            result.error = (
                f"{calendar.name or 'A calendar'} could not be synced. "
                "The server log has the details."
            )

    if result.error:
        _record_failure(db, connection, result.error)
    else:
        connection.last_sync_at = utcnow()
        connection.last_sync_error = None
        connection.last_sync_error_at = None
        connection.status = ConnectionStatus.CONNECTED.value
        activity_service.log(
            db,
            workspace_id=workspace.id,
            activity_type=ActivityType.CALENDAR_SYNCED,
            message=(
                f"{adapter.display_name} synced — "
                f"{result.events_created} new, {result.events_updated} updated"
            ),
            person_id=connection.person_id,
        )
        db.commit()

    result.finished_at = utcnow()
    return result


def _record_failure(db: Session, connection: CalendarConnection, message: str) -> None:
    connection.last_sync_error = message
    connection.last_sync_error_at = utcnow()
    if connection.status == ConnectionStatus.CONNECTED.value:
        connection.status = ConnectionStatus.ERROR.value
    db.commit()


def _sync_calendar(
    db: Session,
    workspace: Workspace,
    connection: CalendarConnection,
    calendar: ExternalCalendar,
    *,
    adapter,
    access_token: str,
    start,
    end,
    result: SyncResultOut,
    full: bool,
) -> None:
    page = adapter.list_events(
        access_token,
        calendar_id=calendar.provider_calendar_id,
        start=start,
        end=end,
        sync_token=None if full else calendar.sync_token,
    )

    existing = {
        event.provider_event_id: event
        for event in db.scalars(
            select(CalendarEvent).where(
                CalendarEvent.external_calendar_id == calendar.id
            )
        )
        if event.provider_event_id
    }

    # The same meeting invited to two connected accounts appears once per
    # account with a different provider id but the same iCalUID (spec §7).
    #
    # The key includes the start time, not just the UID: with
    # `singleEvents=true` Google gives every instance of a recurring series the
    # same iCalUID, so deduplicating on the UID alone would collapse a weekly
    # meeting into a single event. Only calendars *other* than this one are
    # considered, so a series inside one calendar is never affected.
    seen_elsewhere = {
        (uid, starts_at)
        for uid, starts_at in db.execute(
            select(CalendarEvent.ical_uid, CalendarEvent.starts_at).where(
                CalendarEvent.person_id == connection.person_id,
                CalendarEvent.ical_uid.is_not(None),
                CalendarEvent.external_calendar_id.is_not(None),
                CalendarEvent.external_calendar_id != calendar.id,
            )
        )
        if uid
    }

    for incoming in page.events:
        current = existing.get(incoming.provider_event_id)
        if current is None:
            if (
                incoming.ical_uid
                and (incoming.ical_uid, incoming.starts_at) in seen_elsewhere
            ):
                result.duplicates_skipped += 1
                continue
            _create_event(db, workspace, connection, calendar, incoming, result)
        else:
            _update_event(db, workspace, current, incoming, result)

    for deleted_id in page.deleted_event_ids:
        event = existing.get(deleted_id)
        if event is not None and event.deleted_at is None:
            _cancel_event(db, workspace, event, result)

    calendar.sync_token = page.next_sync_token
    calendar.last_synced_at = utcnow()
    db.commit()


def _create_event(
    db: Session,
    workspace: Workspace,
    connection: CalendarConnection,
    calendar: ExternalCalendar,
    incoming: NormalizedEvent,
    result: SyncResultOut,
) -> CalendarEvent:
    event = CalendarEvent(
        person_id=connection.person_id,
        external_calendar_id=calendar.id,
        connection_id=connection.id,
        provider=connection.provider,
        provider_event_id=incoming.provider_event_id,
        ical_uid=incoming.ical_uid,
        etag=incoming.etag,
        source=EventSource.EXTERNAL_PROVIDER.value,
        last_synced_at=utcnow(),
    )
    _apply_incoming(event, incoming)
    event.classification = _initial_classification(incoming).value
    _run_detection(workspace, event, result)
    db.add(event)
    result.events_created += 1
    return event


def _update_event(
    db: Session,
    workspace: Workspace,
    event: CalendarEvent,
    incoming: NormalizedEvent,
    result: SyncResultOut,
) -> None:
    previous_start = event.starts_at
    previous_end = event.ends_at
    was_deleted = event.deleted_at is not None

    _apply_incoming(event, incoming)
    event.etag = incoming.etag
    event.last_synced_at = utcnow()
    event.deleted_at = None

    if not event.classification_locked:
        _run_detection(workspace, event, result)

    result.events_updated += 1

    if event.starts_at != previous_start or event.ends_at != previous_end:
        _propagate_reschedule(db, workspace, event, previous_start, result)
    elif was_deleted:
        _restore_interview(db, workspace, event)


def _apply_incoming(event: CalendarEvent, incoming: NormalizedEvent) -> None:
    event.title = incoming.title[:1024]
    event.description = incoming.description
    event.location = incoming.location
    event.meeting_url = incoming.meeting_url
    event.organizer_email = incoming.organizer_email
    event.organizer_name = incoming.organizer_name
    event.attendees = incoming.attendees or None
    event.starts_at = incoming.starts_at
    event.ends_at = incoming.ends_at
    event.start_timezone = incoming.start_timezone
    event.end_timezone = incoming.end_timezone
    event.is_all_day = incoming.is_all_day
    event.is_recurring = incoming.is_recurring
    event.status = incoming.status.value
    event.raw = incoming.raw
    event.ical_uid = incoming.ical_uid or event.ical_uid


def _initial_classification(incoming: NormalizedEvent) -> EventClassification:
    """How a freshly imported event is filed before anyone looks at it.

    An imported event counts as an interview by default, which is right for the
    one-off meetings a job search generates and wrong for the furniture of a
    working week. A weekly standup or an all-day "PTO" block would otherwise
    arrive fifty-two times over and drown the funnel, so those two shapes are
    pre-filed as not-an-interview.

    Nothing here is locked: detection still scores the event, and a person can
    reclassify it. This only decides where it starts.
    """
    if incoming.is_recurring or incoming.is_all_day:
        return EventClassification.NORMAL_MEETING
    return EventClassification.UNCLASSIFIED


def _run_detection(
    workspace: Workspace, event: CalendarEvent, result: SyncResultOut
) -> None:
    """Score the event and record the suggestion — never classify it outright."""
    if not workspace.auto_detect_interviews:
        return
    outcome = detection.detect(
        title=event.title,
        description=event.description,
        location=event.location,
        meeting_url=event.meeting_url,
        organizer_email=event.organizer_email,
        organizer_name=event.organizer_name,
        attendee_emails=[
            a.get("email") for a in (event.attendees or []) if a.get("email")
        ],
    )
    event.detection_score = outcome.score
    event.detection_reasons = outcome.reasons
    if outcome.is_suggestion and not event.detection_dismissed:
        result.suggestions_found += 1
    # `classification` stays UNCLASSIFIED. A human decides (spec §8).


# --------------------------------------------------------------------------
# Provider-wins propagation
# --------------------------------------------------------------------------


def _linked_interview(db: Session, event: CalendarEvent) -> InterviewEvent | None:
    return db.scalars(
        select(InterviewEvent).where(InterviewEvent.calendar_event_id == event.id)
    ).first()


def _propagate_reschedule(
    db: Session,
    workspace: Workspace,
    event: CalendarEvent,
    previous_start,
    result: SyncResultOut,
) -> None:
    """The provider moved an event, so the interview moves with it."""
    interview_event = _linked_interview(db, event)
    if interview_event is None:
        return

    interview_event.starts_at = event.starts_at
    interview_event.ends_at = event.ends_at
    interview_event.timezone = event.start_timezone

    stage = db.get(InterviewStage, interview_event.interview_stage_id)
    if stage is None:  # pragma: no cover - FK guarantees otherwise
        return
    # Flush before refreshing: `refresh` reloads the stage's `events`
    # collection from the database, which would otherwise overwrite the new
    # times that were only just assigned in memory.
    db.flush()
    db.refresh(stage)
    from app.domains.interviews.service import recompute_stage_window

    recompute_stage_window(stage)
    if stage.status == InterviewStatus.CANCELLED.value:
        stage.status = InterviewStatus.SCHEDULED.value

    application = db.get(Application, stage.application_id)
    person = db.get(Person, event.person_id)
    result.interviews_rescheduled += 1
    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.STAGE_RESCHEDULED,
        message=(
            f"{application.company_name if application else 'Interview'} "
            f"{stage.name} moved from {previous_start:%b %-d %H:%M} to "
            f"{event.starts_at:%b %-d %H:%M} (from {person.display_name if person else 'the'} calendar)"
        ),
        person_id=event.person_id,
        application_id=stage.application_id,
        interview_stage_id=stage.id,
        meta={"source": "calendar_sync"},
    )


def _cancel_event(
    db: Session, workspace: Workspace, event: CalendarEvent, result: SyncResultOut
) -> None:
    """The provider removed the event, so the interview is cancelled too."""
    event.deleted_at = utcnow()
    event.status = EventStatus.CANCELLED.value
    result.events_deleted += 1

    interview_event = _linked_interview(db, event)
    if interview_event is None:
        return

    stage = db.get(InterviewStage, interview_event.interview_stage_id)
    if stage is None:  # pragma: no cover
        return

    # Only cancel the whole stage once every one of its slots is gone — a
    # four-slot loop losing one block is not a cancelled interview.
    db.refresh(stage)
    live_slots = [
        slot
        for slot in stage.events
        if slot.id != interview_event.id
        and (
            slot.calendar_event_id is None
            or (
                (linked := db.get(CalendarEvent, slot.calendar_event_id)) is not None
                and linked.deleted_at is None
            )
        )
    ]
    if live_slots:
        return

    if stage.status not in (
        InterviewStatus.COMPLETED.value,
        InterviewStatus.CANCELLED.value,
    ):
        stage.status = InterviewStatus.CANCELLED.value
        if stage.outcome == InterviewOutcome.PENDING.value:
            stage.outcome = InterviewOutcome.CANCELLED.value
        result.interviews_cancelled += 1

        application = db.get(Application, stage.application_id)
        activity_service.log(
            db,
            workspace_id=workspace.id,
            activity_type=ActivityType.STAGE_STATUS_CHANGED,
            message=(
                f"{application.company_name if application else 'Interview'} "
                f"{stage.name} was cancelled in the calendar"
            ),
            person_id=event.person_id,
            application_id=stage.application_id,
            interview_stage_id=stage.id,
            meta={"source": "calendar_sync", "to": InterviewStatus.CANCELLED.value},
        )


def _restore_interview(db: Session, workspace: Workspace, event: CalendarEvent) -> None:
    """An event that came back from the dead un-cancels its interview."""
    interview_event = _linked_interview(db, event)
    if interview_event is None:
        return
    stage = db.get(InterviewStage, interview_event.interview_stage_id)
    if stage is not None and stage.status == InterviewStatus.CANCELLED.value:
        stage.status = InterviewStatus.SCHEDULED.value
        if stage.outcome == InterviewOutcome.CANCELLED.value:
            stage.outcome = InterviewOutcome.PENDING.value


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------


def sync_person(
    db: Session, workspace: Workspace, person_id: str, *, full: bool = False
) -> SyncSummaryOut:
    connections = list(
        db.scalars(
            select(CalendarConnection).where(CalendarConnection.person_id == person_id)
        )
    )
    return _run(db, workspace, connections, full=full)


def sync_one(
    db: Session, workspace: Workspace, connection_id: str, *, full: bool = False
) -> SyncResultOut:
    connection = db.get(CalendarConnection, connection_id)
    if connection is None:
        raise NotFoundError(
            "That calendar connection could not be found.", code="connection_not_found"
        )
    return sync_connection(db, workspace, connection, full=full)


def sync_all(db: Session, workspace: Workspace, *, full: bool = False) -> SyncSummaryOut:
    connections = list(
        db.scalars(
            select(CalendarConnection)
            .join(Person, Person.id == CalendarConnection.person_id)
            .where(
                Person.workspace_id == workspace.id,
                CalendarConnection.status != ConnectionStatus.DISCONNECTED.value,
            )
        )
    )
    return _run(db, workspace, connections, full=full)


def _run(
    db: Session,
    workspace: Workspace,
    connections: list[CalendarConnection],
    *,
    full: bool,
) -> SyncSummaryOut:
    summary = SyncSummaryOut()
    for connection in connections:
        try:
            result = sync_connection(db, workspace, connection, full=full)
        except Exception:
            # Same reasoning one level up: syncing three calendars should not
            # be all-or-nothing because one account is in a bad state.
            logger.exception("unexpected error syncing connection %s", connection.id)
            db.rollback()
            message = (
                "That calendar account could not be synced. The server log has "
                "the details."
            )
            _record_failure(db, connection, message)
            result = SyncResultOut(
                connection_id=connection.id,
                provider=connection.provider,
                started_at=utcnow(),
                finished_at=utcnow(),
                error=message,
            )

        summary.results.append(result)
        summary.total_events += result.events_created + result.events_updated
        if result.error:
            summary.errors.append(result.error)
    return summary


def classify_event(
    db: Session,
    workspace: Workspace,
    event: CalendarEvent,
    classification: EventClassification,
) -> CalendarEvent:
    """Record a human classification and stop detection overriding it."""
    event.classification = classification.value
    event.classification_locked = True
    if classification is EventClassification.IGNORED:
        event.detection_dismissed = True

    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.CALENDAR_EVENT_CLASSIFIED,
        message=f'"{event.title}" marked as {classification.value.replace("_", " ")}',
        person_id=event.person_id,
    )
    db.commit()
    return event
