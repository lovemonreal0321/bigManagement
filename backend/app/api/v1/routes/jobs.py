"""Job endpoints — offers, employment, and payday tracking."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core import permissions
from app.core.deps import CurrentUser, CurrentWorkspace, DbSession, SelectedPeople
from app.domains.jobs import service as job_service
from app.schemas.common import OkResponse
from app.schemas.job import JobCreate, JobOut, JobSummary, JobUpdate

router = APIRouter(prefix="/jobs", tags=["jobs"])


class EndJobRequest(BaseModel):
    end_date: date | None = None
    reason: str | None = None
    note: str | None = None


@router.get("", response_model=list[JobOut])
def list_jobs(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    status: Annotated[list[str] | None, Query()] = None,
    include_ended: bool = True,
) -> list[JobOut]:
    jobs = job_service.list_jobs(
        db, workspace, scope.ids, statuses=status, include_ended=include_ended
    )
    return [job_service.decorate(job) for job in jobs]


@router.get("/summary", response_model=JobSummary)
def job_summary(
    db: DbSession, workspace: CurrentWorkspace, scope: SelectedPeople
) -> JobSummary:
    """The Jobs dashboard for whoever is selected."""
    return job_service.build_summary(db, workspace, scope.people)


@router.post("", response_model=JobOut, status_code=201)
def create_job(
    payload: JobCreate,
    db: DbSession,
    workspace: CurrentWorkspace,
    user: CurrentUser,
) -> JobOut:
    permissions.require_person_edit(user, payload.person_id, what="this person's jobs")
    return job_service.decorate(job_service.create_job(db, workspace, payload))


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: DbSession, workspace: CurrentWorkspace) -> JobOut:
    return job_service.decorate(job_service.get_job(db, workspace, job_id))


@router.patch("/{job_id}", response_model=JobOut)
def update_job(
    job_id: str,
    payload: JobUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
    user: CurrentUser,
) -> JobOut:
    job = job_service.get_job(db, workspace, job_id)
    permissions.require_person_edit(user, job.person_id, what="this job")
    return job_service.decorate(job_service.update_job(db, workspace, job_id, payload))


@router.post("/{job_id}/end", response_model=JobOut)
def end_job(
    job_id: str,
    payload: EndJobRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
    user: CurrentUser,
) -> JobOut:
    """Close a job out — resigned, laid off, contract ended."""
    job = job_service.get_job(db, workspace, job_id)
    permissions.require_person_edit(user, job.person_id, what="this job")
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
    job_id: str, db: DbSession, workspace: CurrentWorkspace, user: CurrentUser
) -> OkResponse:
    job = job_service.get_job(db, workspace, job_id)
    permissions.require_person_edit(user, job.person_id, what="this job")
    job_service.delete_job(db, workspace, job_id)
    return OkResponse(message="Job removed.")
