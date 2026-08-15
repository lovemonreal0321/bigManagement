"""Calendar connections, OAuth orchestration, event feed and linking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.core.security import create_state_token, decode_state_token
from app.core.timeutils import local_date, utcnow
from app.domains.activity import service as activity_service
from app.domains.calendar.conflicts import find_conflicts
from app.domains.calendar.providers import available_providers, get_adapter
from app.domains.interviews.types import TypeRegistry, load_registry, stage_badge
from app.enums import (
    ActivityType,
    ApplicationStatus,
    CalendarProvider,
    ConnectionStatus,
    EventClassification,
    EventSource,
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
from app.schemas.calendar import (
    CalendarConnectionOut,
    CalendarEventOut,
    CalendarFeedEvent,
    CalendarFeedOut,
    CreateApplicationFromEvent,
    ExternalCalendarOut,
    InterviewSuggestionOut,
    LinkEventToApplication,
    ProviderInfo,
)

SETUP_DOC = "See README.md → Google/Microsoft OAuth configuration."


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------


def list_providers() -> list[ProviderInfo]:
    infos = []
    for adapter in available_providers():
        missing = adapter.missing_settings()
        infos.append(
            ProviderInfo(
                key=adapter.key,
                display_name=adapter.display_name,
                is_configured=adapter.is_configured,
                missing_settings=missing,
                setup_hint=(
                    None
                    if adapter.is_configured
                    else f"Set {', '.join(missing)} in backend/.env, then restart. {SETUP_DOC}"
                ),
            )
        )
    return infos


# --------------------------------------------------------------------------
# Connections
# --------------------------------------------------------------------------


def _connection_out(
    connection: CalendarConnection, person: Person | None
) -> CalendarConnectionOut:
    adapter = get_adapter(connection.provider)
    out = CalendarConnectionOut.model_validate(connection)
    out.provider_display_name = adapter.display_name
    out.calendars = [
        ExternalCalendarOut.model_validate(c)
        for c in sorted(connection.calendars, key=lambda c: (not c.is_primary, c.name))
    ]
    if person is not None:
        out.person_name = person.display_name
        out.person_color = person.color
        out.person_initials = person.initials
    return out


def list_connections(
    db: Session, workspace: Workspace, person_ids: list[str] | None = None
) -> list[CalendarConnectionOut]:
    stmt = (
        select(CalendarConnection, Person)
        .join(Person, Person.id == CalendarConnection.person_id)
        .where(Person.workspace_id == workspace.id)
        .order_by(Person.sort_order, Person.name)
    )
    if person_ids is not None:
        stmt = stmt.where(CalendarConnection.person_id.in_(person_ids))
    return [_connection_out(conn, person) for conn, person in db.execute(stmt)]


def get_connection(
    db: Session, workspace: Workspace, connection_id: str
) -> CalendarConnection:
    connection = db.get(CalendarConnection, connection_id)
    if connection is None:
        raise NotFoundError(
            "That calendar connection could not be found.", code="connection_not_found"
        )
    person = db.get(Person, connection.person_id)
    if person is None or person.workspace_id != workspace.id:
        raise NotFoundError(
            "That calendar connection could not be found.", code="connection_not_found"
        )
    return connection


def disconnect(db: Session, workspace: Workspace, connection_id: str) -> None:
    """Forget the tokens and the connection.

    Imported events are kept but detached, so interview history that referenced
    them survives (spec §36).
    """
    connection = get_connection(db, workspace, connection_id)
    person = db.get(Person, connection.person_id)
    adapter = get_adapter(connection.provider)

    for event in db.scalars(
        select(CalendarEvent).where(CalendarEvent.connection_id == connection.id)
    ):
        event.connection_id = None
        event.external_calendar_id = None

    db.delete(connection)
    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.CALENDAR_DISCONNECTED,
        message=(
            f"{adapter.display_name} disconnected for "
            f"{person.display_name if person else 'a person'}"
        ),
        person_id=connection.person_id,
    )
    db.commit()


def update_calendar_selection(
    db: Session, workspace: Workspace, connection_id: str, selected_ids: list[str]
) -> CalendarConnectionOut:
    connection = get_connection(db, workspace, connection_id)
    wanted = set(selected_ids)
    for calendar in connection.calendars:
        calendar.is_selected = calendar.id in wanted
        if not calendar.is_selected:
            # Force a fresh import if it is re-enabled later.
            calendar.sync_token = None
    db.commit()
    person = db.get(Person, connection.person_id)
    return _connection_out(connection, person)


def update_connection_settings(
    db: Session,
    workspace: Workspace,
    connection_id: str,
    *,
    past_days: int | None,
    future_days: int | None,
) -> CalendarConnectionOut:
    connection = get_connection(db, workspace, connection_id)
    if past_days is not None:
        connection.sync_window_past_days = past_days
    if future_days is not None:
        connection.sync_window_future_days = future_days
    # Window changed, so incremental cursors no longer cover the right range.
    for calendar in connection.calendars:
        calendar.sync_token = None
    db.commit()
    return _connection_out(connection, db.get(Person, connection.person_id))


# --------------------------------------------------------------------------
# OAuth
# --------------------------------------------------------------------------


def _redirect_uri(provider: str) -> str:
    return (
        settings.google_redirect_uri
        if provider == CalendarProvider.GOOGLE.value
        else settings.microsoft_redirect_uri
    )


def start_oauth(db: Session, workspace: Workspace, person_id: str, provider: str) -> str:
    person = db.get(Person, person_id)
    if person is None or person.workspace_id != workspace.id:
        raise ValidationError("Unknown person.", code="person_not_found")

    adapter = get_adapter(provider)
    state = create_state_token({"person_id": person.id, "provider": provider})
    return adapter.authorization_url(state=state, redirect_uri=_redirect_uri(provider))


def complete_oauth(
    db: Session, workspace: Workspace, *, state: str, code: str
) -> CalendarConnection:
    claims = decode_state_token(state)
    if not claims:
        raise ValidationError(
            "That sign-in link expired. Please start the connection again.",
            code="invalid_oauth_state",
        )

    person_id = claims.get("person_id", "")
    provider = claims.get("provider", "")
    person = db.get(Person, person_id)
    if person is None or person.workspace_id != workspace.id:
        raise ValidationError("Unknown person.", code="person_not_found")

    adapter = get_adapter(provider)
    tokens, account = adapter.exchange_code(
        code=code, redirect_uri=_redirect_uri(provider)
    )

    connection = db.scalars(
        select(CalendarConnection).where(
            CalendarConnection.person_id == person.id,
            CalendarConnection.provider == provider,
            CalendarConnection.provider_account_id == account.account_id,
        )
    ).first()
    if connection is None:
        connection = CalendarConnection(
            person_id=person.id,
            provider=provider,
            provider_account_id=account.account_id,
        )
        db.add(connection)

    connection.account_email = account.email
    connection.account_name = account.name
    connection.access_token = tokens.access_token
    if tokens.refresh_token:
        connection.refresh_token = tokens.refresh_token
    connection.token_expires_at = tokens.expires_at
    connection.scope = tokens.scope
    connection.status = ConnectionStatus.CONNECTED.value
    connection.last_sync_error = None
    connection.last_sync_error_at = None
    db.flush()

    _refresh_calendar_list(db, connection, adapter, tokens.access_token)

    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.CALENDAR_CONNECTED,
        message=(
            f"{adapter.display_name} connected for {person.display_name}"
            + (f" ({account.email})" if account.email else "")
        ),
        person_id=person.id,
    )
    db.commit()
    return connection


def _refresh_calendar_list(
    db: Session, connection: CalendarConnection, adapter, access_token: str
) -> None:
    remote = adapter.list_calendars(access_token)
    existing = {c.provider_calendar_id: c for c in connection.calendars}
    first_connect = not existing

    for entry in remote:
        calendar = existing.get(entry.id)
        if calendar is None:
            calendar = ExternalCalendar(
                connection_id=connection.id,
                provider_calendar_id=entry.id,
                # On a first connect, sync the primary calendar only. Pulling
                # every shared/holiday calendar by default would flood the app.
                is_selected=entry.is_primary or not first_connect,
            )
            db.add(calendar)
        calendar.name = entry.name
        calendar.description = entry.description
        calendar.timezone = entry.timezone
        calendar.color = entry.color
        calendar.is_primary = entry.is_primary
        calendar.can_write = entry.can_write
    db.flush()


def refresh_calendars(
    db: Session, workspace: Workspace, connection_id: str
) -> CalendarConnectionOut:
    from app.domains.calendar.sync import ensure_access_token

    connection = get_connection(db, workspace, connection_id)
    adapter = get_adapter(connection.provider)
    access_token = ensure_access_token(db, connection)
    _refresh_calendar_list(db, connection, adapter, access_token)
    db.commit()
    return _connection_out(connection, db.get(Person, connection.person_id))


# --------------------------------------------------------------------------
# Calendar feed
# --------------------------------------------------------------------------


@dataclass
class FeedFilters:
    type_keys: list[str] = field(default_factory=list)
    stage_statuses: list[str] = field(default_factory=list)
    external_calendar_ids: list[str] = field(default_factory=list)
    show_non_interview: bool = True
    classifications: list[str] = field(default_factory=list)


def build_feed(
    db: Session,
    workspace: Workspace,
    people: list[Person],
    *,
    start: datetime,
    end: datetime,
    filters: FeedFilters | None = None,
    include_conflicts: bool = True,
) -> CalendarFeedOut:
    """Every block to draw on the calendar grid, from both sources."""
    filters = filters or FeedFilters()
    registry = load_registry(db, workspace.id)
    person_ids = [p.id for p in people]
    by_person = {p.id: p for p in people}

    feed = CalendarFeedOut(start=start, end=end, person_ids=person_ids)
    if not person_ids:
        return feed

    # -- interviews --------------------------------------------------------
    stmt = (
        select(InterviewEvent, InterviewStage, Application, Person)
        .join(InterviewStage, InterviewStage.id == InterviewEvent.interview_stage_id)
        .join(Application, Application.id == InterviewStage.application_id)
        .join(Person, Person.id == Application.person_id)
        .where(
            Application.person_id.in_(person_ids),
            Application.archived_at.is_(None),
            InterviewEvent.starts_at < end,
            InterviewEvent.ends_at > start,
        )
        .order_by(InterviewEvent.starts_at)
    )
    if filters.type_keys:
        stmt = stmt.where(
            InterviewStage.type_key.in_(filters.type_keys)
            | InterviewEvent.type_key.in_(filters.type_keys)
        )
    if filters.stage_statuses:
        stmt = stmt.where(InterviewStage.status.in_(filters.stage_statuses))

    linked_calendar_event_ids: set[str] = set()
    for event, stage, application, person in db.execute(stmt):
        if event.calendar_event_id:
            linked_calendar_event_ids.add(event.calendar_event_id)
        info = registry.get(event.type_key or stage.type_key)
        feed.events.append(
            CalendarFeedEvent(
                id=f"interview:{event.id}",
                kind="interview",
                person_id=person.id,
                person_name=person.display_name,
                person_color=person.color,
                person_initials=person.initials,
                title=event.title,
                starts_at=event.starts_at,
                ends_at=event.ends_at,
                timezone=event.timezone or person.timezone,
                location=event.location,
                meeting_url=event.meeting_url,
                application_id=application.id,
                interview_stage_id=stage.id,
                interview_event_id=event.id,
                calendar_event_id=event.calendar_event_id,
                company_name=application.company_name,
                job_title=application.job_title,
                stage_badge=stage_badge(stage.round_number, info.short_label),
                type_key=info.key,
                type_label=info.label,
                type_short_label=info.short_label,
                round_number=stage.round_number,
                stage_status=stage.status,
                stage_outcome=stage.outcome,
            )
        )

    # -- external events ---------------------------------------------------
    if filters.show_non_interview or filters.classifications:
        ext_stmt = select(CalendarEvent).where(
            CalendarEvent.person_id.in_(person_ids),
            CalendarEvent.deleted_at.is_(None),
            CalendarEvent.starts_at < end,
            CalendarEvent.ends_at > start,
        )
        if filters.external_calendar_ids:
            ext_stmt = ext_stmt.where(
                CalendarEvent.external_calendar_id.in_(filters.external_calendar_ids)
            )
        if filters.classifications:
            ext_stmt = ext_stmt.where(
                CalendarEvent.classification.in_(filters.classifications)
            )
        elif not filters.show_non_interview:
            ext_stmt = ext_stmt.where(
                CalendarEvent.classification.in_(
                    [
                        EventClassification.INTERVIEW.value,
                        EventClassification.RECRUITER_CALL.value,
                        EventClassification.ASSESSMENT.value,
                    ]
                )
            )
        else:
            # Events the user explicitly ignored stay hidden.
            ext_stmt = ext_stmt.where(
                CalendarEvent.classification != EventClassification.IGNORED.value
            )

        for event in db.scalars(ext_stmt.order_by(CalendarEvent.starts_at)):
            if event.id in linked_calendar_event_ids:
                continue  # already drawn as its interview
            person = by_person.get(event.person_id)
            if person is None:
                continue
            feed.events.append(
                CalendarFeedEvent(
                    id=f"calendar:{event.id}",
                    kind="external",
                    person_id=person.id,
                    person_name=person.display_name,
                    person_color=person.color,
                    person_initials=person.initials,
                    title=event.title,
                    starts_at=event.starts_at,
                    ends_at=event.ends_at,
                    timezone=event.start_timezone or person.timezone,
                    is_all_day=event.is_all_day,
                    location=event.location,
                    meeting_url=event.meeting_url,
                    calendar_event_id=event.id,
                    classification=event.classification,
                    detection_score=event.detection_score,
                    is_suggestion=(
                        event.detection_score >= 0.5
                        and not event.detection_dismissed
                        and event.classification == EventClassification.UNCLASSIFIED.value
                    ),
                )
            )

    feed.events.sort(key=lambda e: (e.starts_at, e.person_name))

    if include_conflicts:
        feed.conflicts = [
            c.model_dump()
            for c in find_conflicts(db, workspace, people, start=start, end=end)
        ]
    return feed


# --------------------------------------------------------------------------
# Events, classification and linking
# --------------------------------------------------------------------------


def get_event(db: Session, workspace: Workspace, event_id: str) -> CalendarEvent:
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise NotFoundError("That event could not be found.", code="event_not_found")
    person = db.get(Person, event.person_id)
    if person is None or person.workspace_id != workspace.id:
        raise NotFoundError("That event could not be found.", code="event_not_found")
    return event


def event_to_out(
    db: Session, event: CalendarEvent, registry: TypeRegistry
) -> CalendarEventOut:
    out = CalendarEventOut.model_validate(event)
    person = db.get(Person, event.person_id)
    if person is not None:
        out.person_name = person.display_name
        out.person_color = person.color
        out.person_initials = person.initials
    if event.external_calendar_id:
        calendar = db.get(ExternalCalendar, event.external_calendar_id)
        out.calendar_name = calendar.name if calendar else None

    link = db.scalars(
        select(InterviewEvent).where(InterviewEvent.calendar_event_id == event.id)
    ).first()
    if link is not None:
        stage = db.get(InterviewStage, link.interview_stage_id)
        if stage is not None:
            application = db.get(Application, stage.application_id)
            info = registry.get(stage.type_key)
            out.interview_stage_id = stage.id
            out.application_id = stage.application_id
            out.stage_badge = stage_badge(stage.round_number, info.short_label)
            out.stage_status = stage.status
            out.stage_outcome = stage.outcome
            out.round_number = stage.round_number
            out.type_key = info.key
            out.type_label = info.label
            if application is not None:
                out.company_name = application.company_name
                out.job_title = application.job_title
    return out


def list_suggestions(
    db: Session, workspace: Workspace, person_ids: list[str], *, limit: int = 25
) -> list[InterviewSuggestionOut]:
    """"Possible interview detected" cards (spec §8)."""
    if not person_ids:
        return []
    registry = load_registry(db, workspace.id)

    linked_ids = {
        cid
        for cid in db.scalars(
            select(InterviewEvent.calendar_event_id).where(
                InterviewEvent.calendar_event_id.is_not(None)
            )
        )
        if cid
    }

    events = db.scalars(
        select(CalendarEvent)
        .where(
            CalendarEvent.person_id.in_(person_ids),
            CalendarEvent.deleted_at.is_(None),
            CalendarEvent.detection_dismissed.is_(False),
            CalendarEvent.detection_score >= 0.5,
            CalendarEvent.classification == EventClassification.UNCLASSIFIED.value,
            CalendarEvent.ends_at >= utcnow(),
        )
        .order_by(CalendarEvent.starts_at)
        .limit(limit * 2)
    )

    suggestions: list[InterviewSuggestionOut] = []
    for event in events:
        if event.id in linked_ids:
            continue
        person = db.get(Person, event.person_id)
        outcome = _redetect(event)
        suggestions.append(
            InterviewSuggestionOut(
                event_id=event.id,
                person_id=event.person_id,
                person_name=person.display_name if person else "",
                person_color=person.color if person else "#64748b",
                title=event.title,
                starts_at=event.starts_at,
                ends_at=event.ends_at,
                score=event.detection_score,
                reasons=event.detection_reasons or [],
                suggested_company=outcome.suggested_company,
                suggested_type=outcome.suggested_type,
                suggested_type_label=(
                    registry.label(outcome.suggested_type)
                    if outcome.suggested_type
                    else None
                ),
                suggested_round=outcome.suggested_round,
                meeting_url=event.meeting_url,
            )
        )
        if len(suggestions) >= limit:
            break
    return suggestions


def _redetect(event: CalendarEvent):
    from app.domains.calendar import detection

    return detection.detect(
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


def dismiss_suggestion(
    db: Session, workspace: Workspace, event_id: str, dismissed: bool = True
) -> CalendarEvent:
    event = get_event(db, workspace, event_id)
    event.detection_dismissed = dismissed
    db.commit()
    return event


def link_event_to_application(
    db: Session, workspace: Workspace, event_id: str, payload: LinkEventToApplication
) -> InterviewStage:
    """Attach an imported event to an application, creating a stage if needed."""
    from app.domains.applications.service import get_application, touch
    from app.domains.interviews.service import recompute_stage_window
    from app.domains.interviews.types import default_stage_name

    event = get_event(db, workspace, event_id)
    application = get_application(db, workspace, payload.application_id)
    registry = load_registry(db, workspace.id)

    if application.person_id != event.person_id:
        raise ValidationError(
            "That event belongs to a different person than the application.",
            code="person_mismatch",
        )

    existing_link = db.scalars(
        select(InterviewEvent).where(InterviewEvent.calendar_event_id == event.id)
    ).first()
    if existing_link is not None:
        raise ValidationError(
            "That event is already linked to an interview.", code="already_linked"
        )

    if payload.interview_stage_id:
        stage = db.get(InterviewStage, payload.interview_stage_id)
        if stage is None or stage.application_id != application.id:
            raise ValidationError(
                "That interview does not belong to this application.",
                code="stage_mismatch",
            )
    else:
        detected = _redetect(event)
        type_key = payload.type_key or detected.suggested_type or "other"
        if type_key not in registry.keys:
            type_key = "other"
        info = registry.get(type_key)
        round_number = payload.round_number or detected.suggested_round
        sequence = (
            db.scalar(
                select(InterviewStage.sequence)
                .where(InterviewStage.application_id == application.id)
                .order_by(InterviewStage.sequence.desc())
                .limit(1)
            )
            or 0
        ) + 1
        stage = InterviewStage(
            application_id=application.id,
            type_key=type_key,
            round_number=round_number,
            sequence=sequence,
            name=payload.stage_name or default_stage_name(round_number, info.label),
            status=InterviewStatus.SCHEDULED.value,
        )
        db.add(stage)
        db.flush()

    interview_event = InterviewEvent(
        interview_stage_id=stage.id,
        calendar_event_id=event.id,
        title=event.title[:512],
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        timezone=event.start_timezone,
        location=event.location,
        meeting_url=event.meeting_url,
        # It came from the provider, so write-back must never touch it.
        source=EventSource.EXTERNAL_PROVIDER.value,
    )
    db.add(interview_event)
    db.flush()
    db.refresh(stage)
    recompute_stage_window(stage)

    event.classification = EventClassification.INTERVIEW.value
    event.classification_locked = True
    touch(application)

    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.CALENDAR_EVENT_LINKED,
        message=(
            f'"{event.title}" linked to {application.company_name} — {stage.name}'
        ),
        person_id=event.person_id,
        application_id=application.id,
        interview_stage_id=stage.id,
    )
    db.commit()
    return stage


def create_application_from_event(
    db: Session, workspace: Workspace, event_id: str, payload: CreateApplicationFromEvent
) -> Application:
    """Create a new application (plus its first stage) from an imported event."""
    from app.domains.applications.service import create_application
    from app.schemas.application import ApplicationCreate

    event = get_event(db, workspace, event_id)
    person_id = payload.person_id or event.person_id
    person = db.get(Person, person_id)
    if person is None or person.workspace_id != workspace.id:
        raise ValidationError("Unknown person.", code="person_not_found")

    application = create_application(
        db,
        workspace,
        ApplicationCreate(
            person_id=person.id,
            company_name=payload.company_name,
            job_title=payload.job_title,
            applied_date=payload.applied_date
            or local_date(event.starts_at, person.timezone),
            status=ApplicationStatus.INTERVIEWING,
        ),
    )

    link_event_to_application(
        db,
        workspace,
        event_id,
        LinkEventToApplication(
            application_id=application.id,
            type_key=payload.type_key,
            round_number=payload.round_number,
            stage_name=payload.stage_name,
        ),
    )
    return application
