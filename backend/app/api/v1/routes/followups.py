"""Follow-up endpoints (spec §19-§21, §31)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.core import permissions
from app.core.deps import CurrentUser, CurrentWorkspace, DbSession, SelectedPeople
from app.domains.followups import rules as followup_rules
from app.domains.followups import service as followup_service
from app.schemas.common import OkResponse
from app.schemas.followup import (
    FollowUpBoard,
    FollowUpCreate,
    FollowUpOut,
    FollowUpSnooze,
    FollowUpSuggestion,
    FollowUpUpdate,
)

router = APIRouter(prefix="/follow-ups", tags=["follow-ups"])


@router.get("", response_model=list[FollowUpOut])
def list_follow_ups(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    status: Annotated[list[str] | None, Query()] = None,
    application_id: str | None = None,
    limit: int = Query(200, ge=1, le=500),
) -> list[FollowUpOut]:
    return followup_service.list_follow_ups(
        db,
        workspace,
        scope.ids,
        statuses=status,
        application_id=application_id,
        limit=limit,
    )


@router.get("/board", response_model=FollowUpBoard)
def get_board(
    db: DbSession, workspace: CurrentWorkspace, scope: SelectedPeople
) -> FollowUpBoard:
    return followup_service.build_board(db, workspace, scope.ids)


@router.get("/suggestions", response_model=list[FollowUpSuggestion])
def get_suggestions(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    limit: int = Query(25, ge=1, le=50),
) -> list[FollowUpSuggestion]:
    """Proposed follow-ups awaiting accept / modify / dismiss (spec §20)."""
    return followup_rules.collect_suggestions(db, workspace, scope.ids, limit=limit)


@router.post("", response_model=FollowUpOut, status_code=201)
def create_follow_up(
    payload: FollowUpCreate,
    db: DbSession,
    workspace: CurrentWorkspace,
    user: CurrentUser,
) -> FollowUpOut:
    permissions.require_application_edit(db, user, payload.application_id)
    follow_up = followup_service.create_follow_up(db, workspace, payload)
    return followup_service.hydrate_one(db, workspace, follow_up)


@router.patch("/{follow_up_id}", response_model=FollowUpOut)
def update_follow_up(
    follow_up_id: str,
    payload: FollowUpUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
    user: CurrentUser,
) -> FollowUpOut:
    permissions.require_follow_up_edit(db, user, follow_up_id)
    follow_up = followup_service.update_follow_up(
        db, workspace, follow_up_id, payload
    )
    return followup_service.hydrate_one(db, workspace, follow_up)


@router.post("/{follow_up_id}/complete", response_model=FollowUpOut)
def complete_follow_up(
    follow_up_id: str, db: DbSession, workspace: CurrentWorkspace, user: CurrentUser
) -> FollowUpOut:
    permissions.require_follow_up_edit(db, user, follow_up_id)
    follow_up = followup_service.complete_follow_up(db, workspace, follow_up_id)
    return followup_service.hydrate_one(db, workspace, follow_up)


@router.get("/{follow_up_id}/next-suggestion", response_model=FollowUpSuggestion | None)
def next_suggestion(
    follow_up_id: str, db: DbSession, workspace: CurrentWorkspace
) -> FollowUpSuggestion | None:
    """After completing one, optionally chain another (spec §21)."""
    follow_up = followup_service.get_follow_up(db, workspace, follow_up_id)
    return followup_rules.suggest_after_follow_up(db, workspace, follow_up)


@router.post("/{follow_up_id}/snooze", response_model=FollowUpOut)
def snooze_follow_up(
    follow_up_id: str,
    payload: FollowUpSnooze,
    db: DbSession,
    workspace: CurrentWorkspace,
    user: CurrentUser,
) -> FollowUpOut:
    permissions.require_follow_up_edit(db, user, follow_up_id)
    follow_up = followup_service.snooze_follow_up(
        db, workspace, follow_up_id, until=payload.until, days=payload.days
    )
    return followup_service.hydrate_one(db, workspace, follow_up)


@router.post("/{follow_up_id}/cancel", response_model=FollowUpOut)
def cancel_follow_up(
    follow_up_id: str, db: DbSession, workspace: CurrentWorkspace, user: CurrentUser
) -> FollowUpOut:
    permissions.require_follow_up_edit(db, user, follow_up_id)
    follow_up = followup_service.cancel_follow_up(db, workspace, follow_up_id)
    return followup_service.hydrate_one(db, workspace, follow_up)


@router.delete("/{follow_up_id}", response_model=OkResponse)
def delete_follow_up(
    follow_up_id: str, db: DbSession, workspace: CurrentWorkspace, user: CurrentUser
) -> OkResponse:
    permissions.require_follow_up_edit(db, user, follow_up_id)
    followup_service.delete_follow_up(db, workspace, follow_up_id)
    return OkResponse(message="Follow-up deleted.")
