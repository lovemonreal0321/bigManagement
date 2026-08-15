"""Calendar endpoints: providers, OAuth, sync, feed, classification (spec §6-§10, §45-§48)."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import CurrentWorkspace, DbSession, SelectedPeople
from app.core.errors import AppError
from app.core.timeutils import utcnow
from app.domains.auth.service import get_workspace
from app.domains.calendar import service as calendar_service
from app.domains.calendar import sync as sync_service
from app.domains.calendar.service import FeedFilters
from app.domains.interviews.types import load_registry
from app.schemas.calendar import (
    CalendarConnectionOut,
    CalendarEventOut,
    CalendarFeedOut,
    CalendarSelectionUpdate,
    ConnectionUpdate,
    CreateApplicationFromEvent,
    DismissSuggestionRequest,
    EventClassificationUpdate,
    InterviewSuggestionOut,
    LinkEventToApplication,
    OAuthStartOut,
    ProviderInfo,
    SyncResultOut,
    SyncSummaryOut,
)
from app.schemas.common import OkResponse
from app.schemas.interview import InterviewStageOut

router = APIRouter(prefix="/calendar", tags=["calendar"])


# --------------------------------------------------------------------------
# Providers and connections
# --------------------------------------------------------------------------


@router.get("/providers", response_model=list[ProviderInfo])
def list_providers() -> list[ProviderInfo]:
    """Which providers this server can talk to.

    Unconfigured providers are still listed, with the exact env vars that are
    missing — the app stays usable without credentials (spec §69).
    """
    return calendar_service.list_providers()


@router.get("/connections", response_model=list[CalendarConnectionOut])
def list_connections(
    db: DbSession, workspace: CurrentWorkspace, scope: SelectedPeople
) -> list[CalendarConnectionOut]:
    return calendar_service.list_connections(db, workspace, scope.ids)


@router.get("/connections/all", response_model=list[CalendarConnectionOut])
def list_all_connections(
    db: DbSession, workspace: CurrentWorkspace
) -> list[CalendarConnectionOut]:
    """Settings page: every connection, ignoring the person filter."""
    return calendar_service.list_connections(db, workspace, None)


@router.patch("/connections/{connection_id}", response_model=CalendarConnectionOut)
def update_connection(
    connection_id: str,
    payload: ConnectionUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> CalendarConnectionOut:
    return calendar_service.update_connection_settings(
        db,
        workspace,
        connection_id,
        past_days=payload.sync_window_past_days,
        future_days=payload.sync_window_future_days,
    )


@router.post(
    "/connections/{connection_id}/calendars", response_model=CalendarConnectionOut
)
def update_calendar_selection(
    connection_id: str,
    payload: CalendarSelectionUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> CalendarConnectionOut:
    return calendar_service.update_calendar_selection(
        db, workspace, connection_id, payload.selected_calendar_ids
    )


@router.post(
    "/connections/{connection_id}/refresh-calendars",
    response_model=CalendarConnectionOut,
)
def refresh_calendars(
    connection_id: str, db: DbSession, workspace: CurrentWorkspace
) -> CalendarConnectionOut:
    return calendar_service.refresh_calendars(db, workspace, connection_id)


@router.delete("/connections/{connection_id}", response_model=OkResponse)
def disconnect(
    connection_id: str, db: DbSession, workspace: CurrentWorkspace
) -> OkResponse:
    calendar_service.disconnect(db, workspace, connection_id)
    return OkResponse(message="Calendar disconnected.")


# --------------------------------------------------------------------------
# OAuth
# --------------------------------------------------------------------------


@router.post("/oauth/{provider}/start", response_model=OAuthStartOut)
def start_oauth(
    provider: str,
    person_id: Annotated[str, Query()],
    db: DbSession,
    workspace: CurrentWorkspace,
) -> OAuthStartOut:
    url = calendar_service.start_oauth(db, workspace, person_id, provider)
    return OAuthStartOut(authorization_url=url)


@router.get("/oauth/{provider}/callback", include_in_schema=False)
def oauth_callback(
    provider: str,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Provider redirect target.

    Deliberately unauthenticated: the browser arrives here straight from
    Google/Microsoft with no Authorization header. Trust comes from the signed
    `state` token, which encodes which person the flow was started for. The
    user is then bounced back into the app with a result banner.
    """
    redirect_base = f"{settings.frontend_url}/settings"

    if error:
        return RedirectResponse(
            f"{redirect_base}?calendar_error={error}", status_code=302
        )
    if not state or not code:
        return RedirectResponse(
            f"{redirect_base}?calendar_error=missing_code", status_code=302
        )

    db = next(get_db())
    try:
        workspace = get_workspace(db)
        connection = calendar_service.complete_oauth(
            db, workspace, state=state, code=code
        )
        # Pull events straight away so the calendar is populated on return.
        # The connection itself succeeded; a sync failure is surfaced in
        # Settings rather than turning this redirect into an error.
        with contextlib.suppress(AppError):
            sync_service.sync_connection(db, workspace, connection, full=True)
        return RedirectResponse(
            f"{redirect_base}?calendar_connected={provider}", status_code=302
        )
    except AppError as exc:
        return RedirectResponse(
            f"{redirect_base}?calendar_error={exc.code}", status_code=302
        )
    finally:
        db.close()


# --------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------


@router.post("/sync", response_model=SyncSummaryOut)
def sync_all(
    db: DbSession, workspace: CurrentWorkspace, full: bool = False
) -> SyncSummaryOut:
    return sync_service.sync_all(db, workspace, full=full)


@router.post("/connections/{connection_id}/sync", response_model=SyncResultOut)
def sync_connection(
    connection_id: str,
    db: DbSession,
    workspace: CurrentWorkspace,
    full: bool = False,
) -> SyncResultOut:
    return sync_service.sync_one(db, workspace, connection_id, full=full)


@router.post("/people/{person_id}/sync", response_model=SyncSummaryOut)
def sync_person(
    person_id: str, db: DbSession, workspace: CurrentWorkspace, full: bool = False
) -> SyncSummaryOut:
    return sync_service.sync_person(db, workspace, person_id, full=full)


# --------------------------------------------------------------------------
# Feed and events
# --------------------------------------------------------------------------


@router.get("/feed", response_model=CalendarFeedOut)
def get_feed(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
    type_key: Annotated[list[str] | None, Query()] = None,
    stage_status: Annotated[list[str] | None, Query()] = None,
    external_calendar_id: Annotated[list[str] | None, Query()] = None,
    classification: Annotated[list[str] | None, Query()] = None,
    show_non_interview: bool = True,
    include_conflicts: bool = True,
) -> CalendarFeedOut:
    """Everything to draw on the calendar grid, from both sources (spec §9, §10)."""
    now = utcnow()
    start = start or now - timedelta(days=7)
    end = end or now + timedelta(days=45)
    filters = FeedFilters(
        type_keys=type_key or [],
        stage_statuses=stage_status or [],
        external_calendar_ids=external_calendar_id or [],
        classifications=classification or [],
        show_non_interview=show_non_interview,
    )
    return calendar_service.build_feed(
        db,
        workspace,
        scope.people,
        start=start,
        end=end,
        filters=filters,
        include_conflicts=include_conflicts,
    )


@router.get("/events/{event_id}", response_model=CalendarEventOut)
def get_event(
    event_id: str, db: DbSession, workspace: CurrentWorkspace
) -> CalendarEventOut:
    event = calendar_service.get_event(db, workspace, event_id)
    return calendar_service.event_to_out(db, event, load_registry(db, workspace.id))


@router.post("/events/{event_id}/classify", response_model=CalendarEventOut)
def classify_event(
    event_id: str,
    payload: EventClassificationUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> CalendarEventOut:
    """Triage an imported event (spec §7)."""
    event = calendar_service.get_event(db, workspace, event_id)
    sync_service.classify_event(db, workspace, event, payload.classification)
    return calendar_service.event_to_out(db, event, load_registry(db, workspace.id))


@router.get("/suggestions", response_model=list[InterviewSuggestionOut])
def list_suggestions(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    limit: int = Query(25, ge=1, le=100),
) -> list[InterviewSuggestionOut]:
    """"Possible interview detected" cards (spec §8)."""
    return calendar_service.list_suggestions(db, workspace, scope.ids, limit=limit)


@router.post("/events/{event_id}/dismiss", response_model=OkResponse)
def dismiss_suggestion(
    event_id: str,
    payload: DismissSuggestionRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> OkResponse:
    calendar_service.dismiss_suggestion(db, workspace, event_id, payload.dismissed)
    return OkResponse(message="Suggestion dismissed.")


@router.post("/events/{event_id}/link", response_model=InterviewStageOut)
def link_event(
    event_id: str,
    payload: LinkEventToApplication,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> InterviewStageOut:
    """Attach an imported event to an application (spec §46)."""
    from app.domains.interviews.serialize import stage_to_out

    stage = calendar_service.link_event_to_application(
        db, workspace, event_id, payload
    )
    db.refresh(stage)
    return stage_to_out(stage, load_registry(db, workspace.id))


@router.post("/events/{event_id}/create-application", status_code=201)
def create_application_from_event(
    event_id: str,
    payload: CreateApplicationFromEvent,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> dict[str, str]:
    """Create a new application straight from an imported event (spec §46)."""
    application = calendar_service.create_application_from_event(
        db, workspace, event_id, payload
    )
    return {"application_id": application.id}
