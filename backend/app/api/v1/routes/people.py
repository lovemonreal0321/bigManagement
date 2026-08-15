"""People endpoints (spec §5)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.deps import CurrentWorkspace, DbSession
from app.domains.people import service as people_service
from app.domains.people.colors import PERSON_COLOR_PALETTE
from app.schemas.common import OkResponse
from app.schemas.person import (
    PersonArchiveCheck,
    PersonCreate,
    PersonOut,
    PersonUpdate,
    PersonWithStats,
)

router = APIRouter(prefix="/people", tags=["people"])


@router.get("", response_model=list[PersonWithStats])
def list_people(
    db: DbSession,
    workspace: CurrentWorkspace,
    include_archived: bool = Query(False),
    with_stats: bool = Query(True),
) -> list[PersonWithStats]:
    people = people_service.list_people(
        db, workspace, include_archived=include_archived
    )
    if not with_stats:
        return [PersonWithStats.model_validate(p) for p in people]

    stats = people_service.get_people_stats(db, workspace, people)
    results = []
    for person in people:
        out = PersonWithStats.model_validate(person)
        for key, value in stats.get(person.id, {}).items():
            setattr(out, key, value)
        results.append(out)
    return results


@router.get("/colors", response_model=list[str])
def list_colors() -> list[str]:
    """The palette the UI offers when picking a person's colour."""
    return PERSON_COLOR_PALETTE


@router.post("", response_model=PersonOut, status_code=201)
def create_person(
    payload: PersonCreate, db: DbSession, workspace: CurrentWorkspace
) -> PersonOut:
    return PersonOut.model_validate(
        people_service.create_person(db, workspace, payload)
    )


@router.get("/{person_id}", response_model=PersonOut)
def get_person(
    person_id: str, db: DbSession, workspace: CurrentWorkspace
) -> PersonOut:
    return PersonOut.model_validate(
        people_service.get_person(db, workspace, person_id)
    )


@router.patch("/{person_id}", response_model=PersonOut)
def update_person(
    person_id: str, payload: PersonUpdate, db: DbSession, workspace: CurrentWorkspace
) -> PersonOut:
    return PersonOut.model_validate(
        people_service.update_person(db, workspace, person_id, payload)
    )


@router.post("/{person_id}/archive", response_model=PersonOut)
def archive_person(
    person_id: str, db: DbSession, workspace: CurrentWorkspace
) -> PersonOut:
    return PersonOut.model_validate(
        people_service.archive_person(db, workspace, person_id)
    )


@router.post("/{person_id}/restore", response_model=PersonOut)
def restore_person(
    person_id: str, db: DbSession, workspace: CurrentWorkspace
) -> PersonOut:
    return PersonOut.model_validate(
        people_service.restore_person(db, workspace, person_id)
    )


@router.get("/{person_id}/deletable", response_model=PersonArchiveCheck)
def check_deletable(
    person_id: str, db: DbSession, workspace: CurrentWorkspace
) -> PersonArchiveCheck:
    can_delete, count = people_service.check_deletable(db, workspace, person_id)
    return PersonArchiveCheck(
        can_delete=can_delete,
        application_count=count,
        reason=(
            None
            if can_delete
            else "This person has application history. Archive them instead."
        ),
    )


@router.delete("/{person_id}", response_model=OkResponse)
def delete_person(
    person_id: str, db: DbSession, workspace: CurrentWorkspace
) -> OkResponse:
    people_service.delete_person(db, workspace, person_id)
    return OkResponse(message="Person deleted.")
