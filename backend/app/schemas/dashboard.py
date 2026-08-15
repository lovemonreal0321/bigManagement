"""Dashboard schemas (spec §22, §23)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.activity import ActivityOut
from app.schemas.analytics import PersonComparisonRow
from app.schemas.application import PipelineColumnOut
from app.schemas.calendar import InterviewSuggestionOut
from app.schemas.followup import FollowUpSuggestion
from app.schemas.interview import UpcomingInterview


class MetricCard(BaseModel):
    key: str
    label: str
    value: int
    #: Optional supporting line, e.g. "3 in the next 7 days".
    hint: str | None = None
    #: Where clicking the card should go.
    href: str | None = None


class AttentionItem(BaseModel):
    """One row of the Needs Attention panel."""

    id: str
    kind: str  # overdue_follow_up | awaiting_result | upcoming_interview
    #                | waiting_too_long | no_activity | scheduling_conflict
    severity: str  # high | medium | low
    person_id: str
    person_name: str
    person_color: str
    person_initials: str
    company_name: str
    job_title: str | None = None
    headline: str
    detail: str
    application_id: str | None = None
    interview_stage_id: str | None = None
    follow_up_id: str | None = None
    stage_badge: str | None = None
    due_date: date | None = None
    happens_at: datetime | None = None
    #: Action keys the UI renders as buttons (spec §22).
    actions: list[str] = Field(default_factory=list)


class DashboardOut(BaseModel):
    person_ids: list[str]
    period_key: str
    metrics: list[MetricCard] = Field(default_factory=list)
    upcoming_interviews: list[UpcomingInterview] = Field(default_factory=list)
    needs_attention: list[AttentionItem] = Field(default_factory=list)
    pipeline: list[PipelineColumnOut] = Field(default_factory=list)
    performance: list[PersonComparisonRow] = Field(default_factory=list)
    recent_activity: list[ActivityOut] = Field(default_factory=list)
    follow_up_suggestions: list[FollowUpSuggestion] = Field(default_factory=list)
    interview_suggestions: list[InterviewSuggestionOut] = Field(default_factory=list)
    #: Interviews whose time has passed and still need an outcome (spec §49).
    awaiting_outcome: list[UpcomingInterview] = Field(default_factory=list)
