"""Interview stage and event endpoints (spec §14-§16, §47, §49)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.core import permissions
from app.core.deps import (
    AdminUser,
    CurrentUser,
    CurrentWorkspace,
    DbSession,
    SelectedPeople,
)
from app.core.errors import ConflictError, ValidationError
from app.domains.interviews import service as interview_service
from app.domains.interviews.serialize import event_to_out, stage_to_out
from app.domains.interviews.types import load_registry
from app.enums import INTERVIEW_TYPE_SHORT_LABELS
from app.models import InterviewType
from app.schemas.common import OkResponse
from app.schemas.interview import (
    InterviewEventCreate,
    InterviewEventOut,
    InterviewEventUpdate,
    InterviewOutcomeUpdate,
    InterviewSearchResult,
    InterviewStageCreate,
    InterviewStageOut,
    InterviewStageReorder,
    InterviewStageUpdate,
    InterviewTypeCreate,
    InterviewTypeOut,
    InterviewTypeUpdate,
    UpcomingInterview,
)

router = APIRouter(tags=["interviews"])


# --------------------------------------------------------------------------
# Interview types
# --------------------------------------------------------------------------

types_router = APIRouter(prefix="/interview-types", tags=["interviews"])


@types_router.get("", response_model=list[InterviewTypeOut])
def list_types(
    db: DbSession, workspace: CurrentWorkspace, include_inactive: bool = False
) -> list[InterviewTypeOut]:
    stmt = select(InterviewType).where(InterviewType.workspace_id == workspace.id)
    if not include_inactive:
        stmt = stmt.where(InterviewType.is_active.is_(True))
    return [
        InterviewTypeOut.model_validate(t)
        for t in db.scalars(stmt.order_by(InterviewType.sort_order, InterviewType.label))
    ]


@types_router.post("", response_model=InterviewTypeOut, status_code=201)
def create_type(
    payload: InterviewTypeCreate,
    db: DbSession,
    workspace: CurrentWorkspace,
    admin: AdminUser,
) -> InterviewTypeOut:
    """Custom interview types (spec §14).

    Workspace-wide vocabulary shared by every person, so administrator-only.
    """
    key = payload.label.strip().lower().replace(" ", "_").replace("-", "_")
    key = "".join(ch for ch in key if ch.isalnum() or ch == "_")[:64]
    if not key:
        raise ValidationError("Give the interview type a name.", code="invalid_type_name")

    existing = db.scalars(
        select(InterviewType).where(
            InterviewType.workspace_id == workspace.id, InterviewType.key == key
        )
    ).first()
    if existing is not None:
        raise ConflictError(
            f"An interview type called {payload.label} already exists.",
            code="type_exists",
        )

    max_order = (
        db.scalar(
            select(InterviewType.sort_order)
            .where(InterviewType.workspace_id == workspace.id)
            .order_by(InterviewType.sort_order.desc())
            .limit(1)
        )
        or 0
    )
    interview_type = InterviewType(
        workspace_id=workspace.id,
        key=key,
        label=payload.label.strip(),
        short_label=(
            payload.short_label or INTERVIEW_TYPE_SHORT_LABELS.get(key, payload.label)
        ).strip()[:32],
        is_builtin=False,
        sort_order=max_order + 1,
        counts_as_technical=payload.counts_as_technical,
        counts_as_final=payload.counts_as_final,
        counts_as_screening=payload.counts_as_screening,
    )
    db.add(interview_type)
    db.commit()
    return InterviewTypeOut.model_validate(interview_type)


@types_router.patch("/{type_id}", response_model=InterviewTypeOut)
def update_type(
    type_id: str,
    payload: InterviewTypeUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
    admin: AdminUser,
) -> InterviewTypeOut:
    interview_type = db.get(InterviewType, type_id)
    if interview_type is None or interview_type.workspace_id != workspace.id:
        raise ValidationError("Unknown interview type.", code="unknown_interview_type")

    data = payload.model_dump(exclude_unset=True)
    if interview_type.is_builtin and "is_active" not in data and len(data) > 0:
        # Built-ins can be renamed or re-flagged, but the key stays fixed so
        # existing stages keep resolving.
        pass
    for key, value in data.items():
        if value is not None:
            setattr(interview_type, key, value)
    db.commit()
    return InterviewTypeOut.model_validate(interview_type)


# --------------------------------------------------------------------------
# Stages
# --------------------------------------------------------------------------


@router.get(
    "/applications/{application_id}/stages", response_model=list[InterviewStageOut]
)
def list_stages(
    application_id: str, db: DbSession, workspace: CurrentWorkspace
) -> list[InterviewStageOut]:
    registry = load_registry(db, workspace.id)
    stages = interview_service.list_stages(db, workspace, application_id)
    return [stage_to_out(s, registry) for s in stages]


@router.post(
    "/applications/{application_id}/stages",
    response_model=InterviewStageOut,
    status_code=201,
)
def create_stage(
    application_id: str,
    payload: InterviewStageCreate,
    db: DbSession,
    workspace: CurrentWorkspace,
    user: CurrentUser,
) -> InterviewStageOut:
    permissions.require_application_edit(db, user, application_id)
    stage = interview_service.create_stage(db, workspace, application_id, payload)
    db.refresh(stage)
    return stage_to_out(stage, load_registry(db, workspace.id))


@router.post(
    "/applications/{application_id}/stages/reorder",
    response_model=list[InterviewStageOut],
)
def reorder_stages(
    application_id: str,
    payload: InterviewStageReorder,
    db: DbSession,
    workspace: CurrentWorkspace,
    user: CurrentUser,
) -> list[InterviewStageOut]:
    permissions.require_application_edit(db, user, application_id)
    stages = interview_service.reorder_stages(
        db, workspace, application_id, payload.stage_ids
    )
    registry = load_registry(db, workspace.id)
    return [stage_to_out(s, registry) for s in stages]


@router.get("/interview-stages/{stage_id}", response_model=InterviewStageOut)
def get_stage(
    stage_id: str, db: DbSession, workspace: CurrentWorkspace
) -> InterviewStageOut:
    stage = interview_service.get_stage(db, workspace, stage_id)
    return stage_to_out(stage, load_registry(db, workspace.id))


@router.patch("/interview-stages/{stage_id}", response_model=InterviewStageOut)
def update_stage(
    stage_id: str,
    payload: InterviewStageUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
    user: CurrentUser,
) -> InterviewStageOut:
    permissions.require_stage_edit(db, user, stage_id)
    stage = interview_service.update_stage(db, workspace, stage_id, payload)
    db.refresh(stage)
    return stage_to_out(stage, load_registry(db, workspace.id))


@router.post("/interview-stages/{stage_id}/outcome", response_model=InterviewStageOut)
def set_outcome(
    stage_id: str,
    payload: InterviewOutcomeUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
    user: CurrentUser,
) -> InterviewStageOut:
    """The "How did it go?" quick action (spec §49)."""
    permissions.require_stage_edit(db, user, stage_id)
    stage = interview_service.set_outcome(db, workspace, stage_id, payload)
    db.refresh(stage)
    return stage_to_out(stage, load_registry(db, workspace.id))


@router.delete("/interview-stages/{stage_id}", response_model=OkResponse)
def delete_stage(
    stage_id: str, db: DbSession, workspace: CurrentWorkspace, user: CurrentUser
) -> OkResponse:
    permissions.require_stage_edit(db, user, stage_id)
    interview_service.delete_stage(db, workspace, stage_id)
    return OkResponse(message="Interview removed.")


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------


@router.post(
    "/interview-stages/{stage_id}/events",
    response_model=InterviewEventOut,
    status_code=201,
)
def add_event(
    stage_id: str,
    payload: InterviewEventCreate,
    db: DbSession,
    workspace: CurrentWorkspace,
    user: CurrentUser,
) -> InterviewEventOut:
    permissions.require_stage_edit(db, user, stage_id)
    event = interview_service.add_event(db, workspace, stage_id, payload)
    stage = interview_service.get_stage(db, workspace, stage_id)
    return event_to_out(event, load_registry(db, workspace.id), stage)


@router.patch("/interview-events/{event_id}", response_model=InterviewEventOut)
def update_event(
    event_id: str,
    payload: InterviewEventUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
    user: CurrentUser,
) -> InterviewEventOut:
    permissions.require_event_edit(db, user, event_id)
    event = interview_service.update_event(db, workspace, event_id, payload)
    stage = interview_service.get_stage(db, workspace, event.interview_stage_id)
    return event_to_out(event, load_registry(db, workspace.id), stage)


@router.delete("/interview-events/{event_id}", response_model=OkResponse)
def delete_event(
    event_id: str, db: DbSession, workspace: CurrentWorkspace, user: CurrentUser
) -> OkResponse:
    permissions.require_event_edit(db, user, event_id)
    interview_service.delete_event(db, workspace, event_id)
    return OkResponse(message="Interview slot removed.")


# --------------------------------------------------------------------------
# Queries
# --------------------------------------------------------------------------


@router.get("/interviews/search", response_model=list[InterviewSearchResult])
def search_interviews(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    q: Annotated[
        str | None,
        Query(description="Matches the interview name, company or job title"),
    ] = None,
    limit: int = Query(25, ge=1, le=100),
) -> list[InterviewSearchResult]:
    """Find a past interview, to hang a later round off it (spec §46)."""
    return interview_service.search_stages(
        db, workspace, person_ids=scope.ids, search=q, limit=limit
    )


@router.get("/interviews/upcoming", response_model=list[UpcomingInterview])
def get_upcoming(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
    limit: int = Query(25, ge=1, le=100),
) -> list[UpcomingInterview]:
    return interview_service.upcoming_interviews(
        db, workspace, scope.ids, start=start, end=end, limit=limit
    )
