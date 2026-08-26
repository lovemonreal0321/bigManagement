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


# --------------------------------------------------------------------------
# Sheet view
#
# A deliberately narrow projection: the spreadsheet shows date, company and the
# job link, and nothing else. Everything richer lives on the detail page.
# --------------------------------------------------------------------------


class SheetRow(ORMModel):
    id: str
    person_id: str
    applied_date: date | None
    company_name: str
    #: Not a column in the sheet, but carried so the UI can show it on hover and
    #: so a row created here can be given a real title later.
    job_title: str
    job_url: str | None
    status: str
    is_archived: bool = False


class SheetDay(BaseModel):
    """One day's worth of rows, plus the count the user asked to see."""

    #: `None` groups applications with no recorded date, which would otherwise
    #: vanish from a date-grouped view.
    date: date | None
    label: str
    count: int
    rows: list[SheetRow]


class SheetTab(BaseModel):
    """One person = one sheet tab."""

    person_id: str
    name: str
    initials: str
    color: str
    total: int
    #: Whether this viewer may type into this person's sheet.
    can_edit: bool


class ApplicationSheet(BaseModel):
    tabs: list[SheetTab]
    person_id: str | None
    can_edit: bool
    days: list[SheetDay]
    #: Rows shown, after any search. `total` ignores the search, so the UI can
    #: say "12 of 47".
    matched: int
    total: int
    busiest_day: date | None = None
    busiest_day_count: int = 0
    #: The single day being shown, or `None` for every day.
    day: date | None = None
    #: True when a `day` was asked for but a search overrode it, so the UI can
    #: say why more than one day is on screen.
    search_ignored_day: bool = False


class BulkApplicationRow(BaseModel):
    """One row of a paste. Only the company is required."""

    company_name: str = Field(min_length=1, max_length=255)
    job_title: str | None = Field(default=None, max_length=255)
    job_url: str | None = None
    applied_date: date | None = None


class BulkApplicationCreate(BaseModel):
    person_id: str
    rows: list[BulkApplicationRow] = Field(min_length=1, max_length=500)


class BulkApplicationResult(BaseModel):
    created: int
    application_ids: list[str]
