"""Application schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

from app.enums import (
    ApplicationStatus,
    EmploymentType,
    PipelineColumn,
    Priority,
    WorkMode,
)
from app.schemas.common import ORMModel
from app.schemas.interview import InterviewStageOut
from app.schemas.person import PersonOut


class ApplicationCreate(BaseModel):
    """Quick Add (spec §50): three required fields, everything else optional."""

    person_id: str
    company_name: str = Field(min_length=1, max_length=255)
    job_title: str = Field(min_length=1, max_length=255)

    job_url: str | None = None
    location: str | None = Field(default=None, max_length=255)
    work_mode: WorkMode = WorkMode.UNKNOWN
    employment_type: EmploymentType = EmploymentType.UNKNOWN
    salary_min: float | None = Field(default=None, ge=0)
    salary_max: float | None = Field(default=None, ge=0)
    salary_currency: str = Field(default="USD", max_length=8)
    hourly_rate: float | None = Field(default=None, ge=0)
    source: str | None = Field(default=None, max_length=120)
    #: Defaults to today in the person's timezone when omitted.
    applied_date: date | None = None
    status: ApplicationStatus = ApplicationStatus.APPLIED
    priority: Priority = Priority.MEDIUM
    notes: str | None = None
    resume_version_id: str | None = None

    @model_validator(mode="after")
    def _check_salary(self) -> ApplicationCreate:
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("The minimum salary cannot be above the maximum")
        return self


class ApplicationUpdate(BaseModel):
    person_id: str | None = None
    company_name: str | None = Field(default=None, min_length=1, max_length=255)
    job_title: str | None = Field(default=None, min_length=1, max_length=255)
    job_url: str | None = None
    location: str | None = Field(default=None, max_length=255)
    work_mode: WorkMode | None = None
    employment_type: EmploymentType | None = None
    salary_min: float | None = Field(default=None, ge=0)
    salary_max: float | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, max_length=8)
    hourly_rate: float | None = Field(default=None, ge=0)
    source: str | None = Field(default=None, max_length=120)
    applied_date: date | None = None
    status: ApplicationStatus | None = None
    priority: Priority | None = None
    notes: str | None = None
    resume_version_id: str | None = None


class ApplicationStatusUpdate(BaseModel):
    """Used by the pipeline drag-and-drop (spec §13)."""

    status: ApplicationStatus | None = None
    column: PipelineColumn | None = None

    @model_validator(mode="after")
    def _need_one(self) -> ApplicationStatusUpdate:
        if self.status is None and self.column is None:
            raise ValueError("Provide either a status or a pipeline column")
        return self


class NextInterviewSummary(BaseModel):
    stage_id: str
    stage_name: str
    stage_badge: str
    type_key: str
    type_short_label: str
    round_number: int | None
    starts_at: datetime
    status: str


class ApplicationOut(ORMModel):
    id: str
    person_id: str
    company_name: str
    job_title: str
    job_url: str | None
    location: str | None
    work_mode: str
    employment_type: str
    salary_min: float | None
    salary_max: float | None
    salary_currency: str
    hourly_rate: float | None
    source: str | None
    applied_date: date | None
    status: str
    priority: str
    notes: str | None
    resume_version_id: str | None
    last_activity_at: datetime
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime

    # -- derived, filled in by the service ---------------------------------
    person: PersonOut | None = None
    pipeline_column: str = PipelineColumn.APPLIED.value
    days_since_activity: int = 0
    stage_count: int = 0
    next_interview: NextInterviewSummary | None = None
    current_stage_badge: str | None = None
    open_follow_up_count: int = 0
    has_overdue_follow_up: bool = False


class ApplicationNoteCreate(BaseModel):
    body: str = Field(min_length=1)


class ApplicationNoteOut(ORMModel):
    id: str
    application_id: str
    body: str
    created_at: datetime
    updated_at: datetime


class ApplicationDetail(ApplicationOut):
    """Everything the Application Detail page needs in one round-trip (spec §17)."""

    stages: list[InterviewStageOut] = Field(default_factory=list)
    notes_log: list[ApplicationNoteOut] = Field(default_factory=list)


class PipelineCard(BaseModel):
    """Compact card for the Kanban board (spec §13)."""

    id: str
    person_id: str
    person_name: str
    person_color: str
    person_initials: str
    company_name: str
    job_title: str
    status: str
    priority: str
    current_stage_badge: str | None
    next_interview: NextInterviewSummary | None
    days_since_activity: int
    open_follow_up_count: int
    has_overdue_follow_up: bool


class PipelineColumnOut(BaseModel):
    key: str
    label: str
    count: int
    cards: list[PipelineCard]


class PipelineOut(BaseModel):
    columns: list[PipelineColumnOut]
    total: int
