"""Application endpoints (spec §11-§13, §17, §32, §50)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import CurrentWorkspace, DbSession, SelectedPeople
from app.domains.applications import service as app_service
from app.domains.applications.service import ApplicationFilters
from app.schemas.application import (
    ApplicationCreate,
    ApplicationDetail,
    ApplicationNoteCreate,
    ApplicationNoteOut,
    ApplicationOut,
    ApplicationStatusUpdate,
    ApplicationUpdate,
    PipelineOut,
)
from app.schemas.common import OkResponse, Page

router = APIRouter(prefix="/applications", tags=["applications"])


def _filters(
    scope: SelectedPeople,
    *,
    status: list[str] | None,
    column: list[str] | None,
    type_key: list[str] | None,
    outcome: list[str] | None,
    work_mode: list[str] | None,
    source: list[str] | None,
    company: str | None,
    q: str | None,
    applied_from: date | None,
    applied_to: date | None,
    has_upcoming_interview: bool | None,
    has_overdue_follow_up: bool | None,
    include_archived: bool,
    sort: str,
) -> ApplicationFilters:
    return ApplicationFilters(
        person_ids=scope.ids,
        statuses=status or [],
        columns=column or [],
        type_keys=type_key or [],
        outcomes=outcome or [],
        work_modes=work_mode or [],
        sources=source or [],
        company=company,
        search=q,
        applied_from=applied_from,
        applied_to=applied_to,
        has_upcoming_interview=has_upcoming_interview,
        has_overdue_follow_up=has_overdue_follow_up,
        include_archived=include_archived,
        sort=sort,
    )


@router.get("", response_model=Page[ApplicationOut])
def list_applications(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    status: Annotated[list[str] | None, Query()] = None,
    column: Annotated[list[str] | None, Query()] = None,
    type_key: Annotated[list[str] | None, Query()] = None,
    outcome: Annotated[list[str] | None, Query()] = None,
    work_mode: Annotated[list[str] | None, Query()] = None,
    source: Annotated[list[str] | None, Query()] = None,
    company: str | None = None,
    q: str | None = None,
    applied_from: date | None = None,
    applied_to: date | None = None,
    has_upcoming_interview: bool | None = None,
    has_overdue_follow_up: bool | None = None,
    include_archived: bool = False,
    sort: str = "last_activity",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[ApplicationOut]:
    filters = _filters(
        scope,
        status=status,
        column=column,
        type_key=type_key,
        outcome=outcome,
        work_mode=work_mode,
        source=source,
        company=company,
        q=q,
        applied_from=applied_from,
        applied_to=applied_to,
        has_upcoming_interview=has_upcoming_interview,
        has_overdue_follow_up=has_overdue_follow_up,
        include_archived=include_archived,
        sort=sort,
    )
    applications, total = app_service.list_applications(
        db, workspace, filters, limit=limit, offset=offset
    )
    items = app_service.decorate_applications(db, workspace, applications)
    return Page[ApplicationOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/pipeline", response_model=PipelineOut)
def get_pipeline(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    q: str | None = None,
    include_archived: bool = False,
) -> PipelineOut:
    filters = ApplicationFilters(
        person_ids=scope.ids, search=q, include_archived=include_archived
    )
    return app_service.build_pipeline(db, workspace, filters)


@router.get("/filter-options")
def filter_options(db: DbSession, workspace: CurrentWorkspace) -> dict[str, list[str]]:
    """Distinct values for the filter dropdowns (spec §32)."""
    return {
        "sources": app_service.distinct_sources(db, workspace),
        "companies": app_service.distinct_companies(db, workspace),
        "outcomes": app_service.stage_outcome_values(),
    }


@router.post("", response_model=ApplicationOut, status_code=201)
def create_application(
    payload: ApplicationCreate, db: DbSession, workspace: CurrentWorkspace
) -> ApplicationOut:
    application = app_service.create_application(db, workspace, payload)
    return app_service.decorate_applications(db, workspace, [application])[0]


@router.get("/{application_id}", response_model=ApplicationDetail)
def get_application(
    application_id: str, db: DbSession, workspace: CurrentWorkspace
) -> ApplicationDetail:
    return app_service.build_detail(db, workspace, application_id)


@router.patch("/{application_id}", response_model=ApplicationOut)
def update_application(
    application_id: str,
    payload: ApplicationUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> ApplicationOut:
    application = app_service.update_application(
        db, workspace, application_id, payload
    )
    return app_service.decorate_applications(db, workspace, [application])[0]


@router.post("/{application_id}/status", response_model=ApplicationOut)
def change_status(
    application_id: str,
    payload: ApplicationStatusUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> ApplicationOut:
    application = app_service.change_status(
        db, workspace, application_id, status=payload.status, column=payload.column
    )
    return app_service.decorate_applications(db, workspace, [application])[0]


@router.post("/{application_id}/archive", response_model=ApplicationOut)
def archive_application(
    application_id: str, db: DbSession, workspace: CurrentWorkspace
) -> ApplicationOut:
    application = app_service.archive_application(db, workspace, application_id)
    return app_service.decorate_applications(db, workspace, [application])[0]


@router.post("/{application_id}/restore", response_model=ApplicationOut)
def restore_application(
    application_id: str, db: DbSession, workspace: CurrentWorkspace
) -> ApplicationOut:
    application = app_service.restore_application(db, workspace, application_id)
    return app_service.decorate_applications(db, workspace, [application])[0]


@router.delete("/{application_id}", response_model=OkResponse)
def delete_application(
    application_id: str, db: DbSession, workspace: CurrentWorkspace
) -> OkResponse:
    app_service.delete_application(db, workspace, application_id)
    return OkResponse(message="Application deleted.")


@router.post(
    "/{application_id}/notes", response_model=ApplicationNoteOut, status_code=201
)
def add_note(
    application_id: str,
    payload: ApplicationNoteCreate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> ApplicationNoteOut:
    return ApplicationNoteOut.model_validate(
        app_service.add_note(db, workspace, application_id, payload.body)
    )


@router.delete("/{application_id}/notes/{note_id}", response_model=OkResponse)
def delete_note(
    application_id: str, note_id: str, db: DbSession, workspace: CurrentWorkspace
) -> OkResponse:
    app_service.delete_note(db, workspace, application_id, note_id)
    return OkResponse(message="Note deleted.")
