"""Interview stage / event schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

from app.enums import InterviewOutcome, InterviewStatus, SyncState
from app.schemas.common import ORMModel

# --------------------------------------------------------------------------
# Interview types
# --------------------------------------------------------------------------


class InterviewTypeOut(ORMModel):
    id: str
    key: str
    label: str
    short_label: str
    is_builtin: bool
    is_active: bool
    sort_order: int
    counts_as_technical: bool
    counts_as_final: bool
    counts_as_screening: bool


class InterviewTypeCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    short_label: str | None = Field(default=None, max_length=32)
    counts_as_technical: bool = False
    counts_as_final: bool = False
    counts_as_screening: bool = False


class InterviewTypeUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    short_label: str | None = Field(default=None, max_length=32)
    is_active: bool | None = None
    counts_as_technical: bool | None = None
    counts_as_final: bool | None = None
    counts_as_screening: bool | None = None


# --------------------------------------------------------------------------
# Interview events (time blocks)
# --------------------------------------------------------------------------


class InterviewEventBase(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    type_key: str | None = Field(default=None, max_length=64)
    starts_at: datetime
    ends_at: datetime | None = None
    timezone: str | None = Field(default=None, max_length=64)
    location: str | None = None
    meeting_url: str | None = None
    interviewer_names: str | None = None

    @model_validator(mode="after")
    def _check_range(self) -> InterviewEventBase:
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("The end time must be after the start time")
        return self


class InterviewEventCreate(InterviewEventBase):
    #: Push this slot to the person's connected calendar (spec §47).
    add_to_calendar: bool = False


class InterviewEventUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    type_key: str | None = Field(default=None, max_length=64)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    timezone: str | None = Field(default=None, max_length=64)
    location: str | None = None
    meeting_url: str | None = None
    interviewer_names: str | None = None
    #: Push the change to the connected calendar (spec §48).
    sync_to_calendar: bool = False


class InterviewEventOut(ORMModel):
    id: str
    interview_stage_id: str
    calendar_event_id: str | None
    title: str
    type_key: str | None
    type_label: str | None = None
    type_short_label: str | None = None
    starts_at: datetime
    ends_at: datetime
    timezone: str | None
    location: str | None
    meeting_url: str | None
    interviewer_names: str | None
    sequence: int
    source: str
    sync_state: str = SyncState.LOCAL_ONLY.value
    sync_error: str | None = None


# --------------------------------------------------------------------------
# Interview stages
# --------------------------------------------------------------------------


class InterviewStageBase(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    type_key: str = Field(default="other", max_length=64)
    round_number: int | None = Field(default=None, ge=0, le=99)
    sequence: int | None = Field(default=None, ge=0)
    status: InterviewStatus | None = None
    outcome: InterviewOutcome | None = None
    result_date: date | None = None
    notes: str | None = None


class InterviewStageCreate(InterviewStageBase):
    events: list[InterviewEventCreate] = Field(default_factory=list)


class InterviewStageUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    type_key: str | None = Field(default=None, max_length=64)
    round_number: int | None = Field(default=None, ge=0, le=99)
    sequence: int | None = Field(default=None, ge=0)
    status: InterviewStatus | None = None
    outcome: InterviewOutcome | None = None
    result_date: date | None = None
    notes: str | None = None


class InterviewOutcomeUpdate(BaseModel):
    """The "How did it go?" quick action (spec §49)."""

    outcome: InterviewOutcome
    status: InterviewStatus | None = None
    result_date: date | None = None
    note: str | None = None
    #: Create the suggested follow-up in the same round-trip.
    create_follow_up: bool = False
    follow_up_due_date: date | None = None


class InterviewStageOut(ORMModel):
    id: str
    application_id: str
    round_number: int | None
    sequence: int
    name: str
    type_key: str
    type_label: str | None = None
    type_short_label: str | None = None
    #: Pre-rendered "R2 · Technical" badge (spec §9).
    stage_badge: str | None = None
    status: str
    outcome: str
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    result_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    events: list[InterviewEventOut] = Field(default_factory=list)
    event_count: int = 0


class InterviewStageReorder(BaseModel):
    stage_ids: list[str] = Field(min_length=1)


class UpcomingInterview(BaseModel):
    """Denormalised row for the dashboard "Upcoming Interviews" list (spec §24)."""

    stage_id: str
    event_id: str | None
    application_id: str
    person_id: str
    person_name: str
    person_color: str
    person_initials: str
    company_name: str
    job_title: str
    stage_name: str
    type_key: str
    type_label: str
    type_short_label: str
    round_number: int | None
    stage_badge: str
    status: str
    outcome: str
    starts_at: datetime
    ends_at: datetime
    timezone: str | None
    meeting_url: str | None
    location: str | None


class InterviewSearchResult(BaseModel):
    """One past interview, found by searching, with enough context to identify it.

    Used when attaching a calendar event to a journey that is already under way:
    people remember "the Anthropic recruiter screen" far more readily than which
    application row it hangs off.
    """

    stage_id: str
    application_id: str
    person_id: str
    company_name: str
    job_title: str
    stage_name: str
    stage_badge: str
    type_key: str
    round_number: int | None
    sequence: int
    status: str
    outcome: str
    scheduled_start: datetime | None
    result_date: date | None
    event_count: int
    #: Round number a following interview would take on this application.
    next_round_number: int
