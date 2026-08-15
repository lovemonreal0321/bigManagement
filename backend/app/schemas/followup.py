"""Follow-up schemas."""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, Field

from app.enums import FollowUpStatus, Priority
from app.schemas.common import ORMModel


class FollowUpCreate(BaseModel):
    application_id: str
    interview_stage_id: str | None = None
    title: str = Field(min_length=1, max_length=255)
    reason: str | None = None
    due_date: date
    due_time: time | None = None
    priority: Priority = Priority.MEDIUM
    notes: str | None = None


class FollowUpUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    reason: str | None = None
    due_date: date | None = None
    due_time: time | None = None
    priority: Priority | None = None
    notes: str | None = None
    status: FollowUpStatus | None = None
    interview_stage_id: str | None = None


class FollowUpSnooze(BaseModel):
    #: Either an explicit date or a number of days from today.
    until: date | None = None
    days: int | None = Field(default=None, ge=1, le=365)


class FollowUpOut(ORMModel):
    id: str
    person_id: str
    application_id: str
    interview_stage_id: str | None
    title: str
    reason: str | None
    due_date: date
    due_time: time | None
    status: str
    priority: str
    completed_at: datetime | None
    snoozed_until: date | None
    notes: str | None
    auto_generated: bool
    rule_key: str
    created_at: datetime
    updated_at: datetime

    # -- derived -----------------------------------------------------------
    computed_status: str
    days_overdue: int | None = None
    days_until_due: int | None = None
    due_description: str = ""

    # -- denormalised context so cards need no extra fetch ------------------
    person_name: str = ""
    person_color: str = ""
    person_initials: str = ""
    company_name: str = ""
    job_title: str = ""
    stage_badge: str | None = None


class FollowUpBoard(BaseModel):
    """The Follow-Ups page, bucketed (spec §31)."""

    overdue: list[FollowUpOut] = Field(default_factory=list)
    due_today: list[FollowUpOut] = Field(default_factory=list)
    upcoming: list[FollowUpOut] = Field(default_factory=list)
    snoozed: list[FollowUpOut] = Field(default_factory=list)
    completed: list[FollowUpOut] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


class FollowUpSuggestion(BaseModel):
    """A proposed follow-up the user can accept, modify or dismiss (spec §20)."""

    rule_key: str
    application_id: str
    interview_stage_id: str | None
    person_id: str
    title: str
    reason: str
    suggested_due_date: date
