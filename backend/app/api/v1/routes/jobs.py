"""Job endpoints — offers, employment, and payday tracking."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core import permissions
from app.core.deps import (
    AdminUser,
    CurrentUser,
    CurrentWorkspace,
    DbSession,
    SelectedPeople,
)
from app.core.errors import NotFoundError
from app.domains.jobs import service as job_service
from app.schemas.common import OkResponse
from app.schemas.job import JobCreate, JobOut, JobSummary, JobUpdate

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _readable_person_ids(user, scope: SelectedPeople) -> list[str]:
    """Intersect the global person filter with whose jobs this user may read.

    Jobs are the one place the workspace is not openly readable, so the scope
    the caller asked for is narrowed rather than trusted.
    """
    permissions.require_jobs_access(user)
    allowed = permissions.visible_job_person_ids(user)
    if allowed is None:
        return scope.ids
    return [person_id for person_id in scope.ids if person_id in allowed]


class EndJobRequest(BaseModel):
    end_date: date | None = None
    reason: str | None = None
    note: str | None = None


@router.get("", response_model=list[JobOut])
def list_jobs(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    user: CurrentUser,
    status: Annotated[list[str] | None, Query()] = None,
    include_ended: bool = True,
) -> list[JobOut]:
    person_ids = _readable_person_ids(user, scope)
    if not person_ids:
        return []
    jobs = job_service.list_jobs(
        db, workspace, person_ids, statuses=status, include_ended=include_ended
    )
    return [job_service.decorate(job) for job in jobs]


@router.get("/summary", response_model=JobSummary)
def job_summary(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    user: CurrentUser,
) -> JobSummary:
    """The Jobs dashboard for whoever is selected, narrowed to what this
    account may see."""
    person_ids = set(_readable_person_ids(user, scope))
    people = [person for person in scope.people if person.id in person_ids]
    return job_service.build_summary(db, workspace, people)


@router.post("", response_model=JobOut, status_code=201)
def create_job(
    payload: JobCreate,
    db: DbSession,
    workspace: CurrentWorkspace,
    admin: AdminUser,
) -> JobOut:
    return job_service.decorate(job_service.create_job(db, workspace, payload))


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: str, db: DbSession, workspace: CurrentWorkspace, user: CurrentUser
) -> JobOut:
    job = job_service.get_job(db, workspace, job_id)
    permissions.require_jobs_access(user)
    allowed = permissions.visible_job_person_ids(user)
    if allowed is not None and job.person_id not in allowed:
        raise NotFoundError("That job could not be found.", code="job_not_found")
    return job_service.decorate(job)


@router.patch("/{job_id}", response_model=JobOut)
def update_job(
    job_id: str,
    payload: JobUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
    admin: AdminUser,
) -> JobOut:
    return job_service.decorate(job_service.update_job(db, workspace, job_id, payload))


@router.post("/{job_id}/end", response_model=JobOut)
def end_job(
    job_id: str,
    payload: EndJobRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
    admin: AdminUser,
) -> JobOut:
    """Close a job out — resigned, laid off, contract ended."""
    return job_service.decorate(
        job_service.end_job(
            db,
            workspace,
            job_id,
            end_date=payload.end_date,
            reason=payload.reason,
            note=payload.note,
        )
    )


@router.delete("/{job_id}", response_model=OkResponse)
def delete_job(
    job_id: str, db: DbSession, workspace: CurrentWorkspace, admin: AdminUser
) -> OkResponse:
    job_service.delete_job(db, workspace, job_id)
    return OkResponse(message="Job removed.")
