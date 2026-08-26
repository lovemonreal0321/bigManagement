"""Job schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

from app.enums import (
    DEFAULT_HOURS_PER_WEEK,
    DEFAULT_WEEKS_PER_YEAR,
    JobEndReason,
    JobStatus,
    JobType,
    PayPeriod,
    SalaryType,
)
from app.schemas.common import ORMModel


class JobBase(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    job_type: JobType = JobType.FULL_TIME
    status: JobStatus = JobStatus.OFFERED
    location: str | None = Field(default=None, max_length=255)

    offered_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    end_reason: JobEndReason | None = None
    end_note: str | None = None

    salary_type: SalaryType = SalaryType.ANNUAL
    annual_amount: float | None = Field(default=None, ge=0)
    hourly_amount: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", max_length=8)
    hours_per_week: float = Field(default=DEFAULT_HOURS_PER_WEEK, gt=0, le=168)
    weeks_per_year: float = Field(default=DEFAULT_WEEKS_PER_YEAR, gt=0, le=53)

    pay_period: PayPeriod = PayPeriod.BIWEEKLY
    first_pay_date: date | None = None

    application_id: str | None = None
    interview_stage_id: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> JobBase:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("A job cannot end before it starts")
        return self


class JobCreate(JobBase):
    person_id: str


class JobUpdate(BaseModel):
    """Every field optional — the form patches whatever changed."""

    company_name: str | None = Field(default=None, min_length=1, max_length=255)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    job_type: JobType | None = None
    status: JobStatus | None = None
    location: str | None = Field(default=None, max_length=255)

    offered_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    end_reason: JobEndReason | None = None
    end_note: str | None = None

    salary_type: SalaryType | None = None
    annual_amount: float | None = Field(default=None, ge=0)
    hourly_amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    hours_per_week: float | None = Field(default=None, gt=0, le=168)
    weeks_per_year: float | None = Field(default=None, gt=0, le=53)

    pay_period: PayPeriod | None = None
    first_pay_date: date | None = None

    application_id: str | None = None
    interview_stage_id: str | None = None
    notes: str | None = None


class PayDateOut(BaseModel):
    date: date
    amount: float | None
    is_next: bool = False


class JobOut(ORMModel):
    id: str
    person_id: str
    workspace_id: str
    company_name: str
    title: str
    job_type: str
    status: str
    location: str | None

    offered_date: date | None
    start_date: date | None
    end_date: date | None
    end_reason: str | None
    end_note: str | None

    salary_type: str
    annual_amount: float | None
    hourly_amount: float | None
    currency: str
    hours_per_week: float
    weeks_per_year: float

    pay_period: str
    first_pay_date: date | None

    application_id: str | None
    interview_stage_id: str | None
    notes: str | None
    created_at: datetime | None = None

    # -- derived -----------------------------------------------------------
    person_name: str = ""
    person_color: str = ""
    person_initials: str = ""
    #: What one cheque is worth, gross.
    gross_per_paycheck: float | None = None
    #: Upcoming paydays, soonest first. Empty once a job has ended.
    upcoming_pay_dates: list[PayDateOut] = Field(default_factory=list)
    next_pay_date: date | None = None
    #: Days worked, or days since starting for a live job.
    tenure_days: int | None = None
    is_live: bool = False
    #: Set when the job came from an application in this workspace.
    application_company: str | None = None
    stage_badge: str | None = None


class JobSummary(BaseModel):
    """The Jobs dashboard, per the selected people."""

    live_count: int
    offered_count: int
    ended_count: int
    #: Summed annual pay across live jobs only — an offer not accepted is not
    #: income, and an ended job is not either.
    total_annual: float
    currency: str
    #: `None` when no live job has a pay schedule.
    next_pay_date: date | None
    next_pay_amount: float | None
    next_pay_job_id: str | None
    by_person: list[JobPersonSummary]


class JobPersonSummary(BaseModel):
    person_id: str
    person_name: str
    person_color: str
    person_initials: str
    live_count: int
    total_annual: float
    next_pay_date: date | None
