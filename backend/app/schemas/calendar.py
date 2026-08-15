"""Calendar schemas.

Note what is absent: no schema here exposes `access_token`, `refresh_token`
or `scope`. OAuth secrets never leave the backend (spec §6).
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.enums import EventClassification
from app.schemas.common import ORMModel

# --------------------------------------------------------------------------
# Providers and connections
# --------------------------------------------------------------------------


class ProviderInfo(BaseModel):
    key: str
    display_name: str
    is_configured: bool
    missing_settings: list[str] = Field(default_factory=list)
    setup_hint: str | None = None


class ExternalCalendarOut(ORMModel):
    id: str
    connection_id: str
    provider_calendar_id: str
    name: str
    description: str | None
    timezone: str | None
    color: str | None
    is_primary: bool
    is_selected: bool
    can_write: bool
    last_synced_at: datetime | None


class CalendarConnectionOut(ORMModel):
    id: str
    person_id: str
    provider: str
    provider_display_name: str = ""
    account_email: str | None
    account_name: str | None
    status: str
    last_sync_at: datetime | None
    last_sync_error: str | None
    last_sync_error_at: datetime | None
    sync_window_past_days: int | None
    sync_window_future_days: int | None
    created_at: datetime
    calendars: list[ExternalCalendarOut] = Field(default_factory=list)
    #: Denormalised for the Settings list.
    person_name: str = ""
    person_color: str = ""
    person_initials: str = ""


class ConnectionUpdate(BaseModel):
    sync_window_past_days: int | None = Field(default=None, ge=1, le=3650)
    sync_window_future_days: int | None = Field(default=None, ge=1, le=3650)


class CalendarSelectionUpdate(BaseModel):
    selected_calendar_ids: list[str]


class OAuthStartOut(BaseModel):
    authorization_url: str


class SyncResultOut(BaseModel):
    connection_id: str
    provider: str
    calendars_synced: int = 0
    events_created: int = 0
    events_updated: int = 0
    events_deleted: int = 0
    duplicates_skipped: int = 0
    interviews_rescheduled: int = 0
    interviews_cancelled: int = 0
    suggestions_found: int = 0
    started_at: datetime
    finished_at: datetime
    error: str | None = None


class SyncSummaryOut(BaseModel):
    results: list[SyncResultOut] = Field(default_factory=list)
    total_events: int = 0
    errors: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------


class CalendarEventOut(ORMModel):
    id: str
    person_id: str
    external_calendar_id: str | None
    provider: str | None
    provider_event_id: str | None
    title: str
    description: str | None
    location: str | None
    meeting_url: str | None
    organizer_email: str | None
    organizer_name: str | None
    starts_at: datetime
    ends_at: datetime
    start_timezone: str | None
    is_all_day: bool
    status: str
    classification: str
    classification_locked: bool
    source: str
    detection_score: float
    detection_reasons: list[str] | None
    detection_dismissed: bool

    # -- denormalised context ----------------------------------------------
    person_name: str = ""
    person_color: str = ""
    person_initials: str = ""
    calendar_name: str | None = None
    #: Set when this event backs an interview.
    interview_stage_id: str | None = None
    application_id: str | None = None
    company_name: str | None = None
    job_title: str | None = None
    stage_badge: str | None = None
    stage_status: str | None = None
    stage_outcome: str | None = None
    round_number: int | None = None
    type_key: str | None = None
    type_label: str | None = None


class EventClassificationUpdate(BaseModel):
    classification: EventClassification


class DismissSuggestionRequest(BaseModel):
    dismissed: bool = True


class LinkEventToApplication(BaseModel):
    """Attach an imported event to an existing application (spec §46)."""

    application_id: str
    interview_stage_id: str | None = None
    #: Used when creating a new stage for this event.
    type_key: str | None = None
    round_number: int | None = None
    stage_name: str | None = None


class CreateApplicationFromEvent(BaseModel):
    """Create an application + stage straight from an imported event (spec §46)."""

    person_id: str | None = None
    company_name: str = Field(min_length=1, max_length=255)
    job_title: str = Field(min_length=1, max_length=255)
    type_key: str = "other"
    round_number: int | None = None
    stage_name: str | None = None
    applied_date: date | None = None


class InterviewSuggestionOut(BaseModel):
    """"Possible interview detected" card (spec §8)."""

    event_id: str
    person_id: str
    person_name: str
    person_color: str
    title: str
    starts_at: datetime
    ends_at: datetime
    score: float
    reasons: list[str]
    suggested_company: str | None
    suggested_type: str | None
    suggested_type_label: str | None
    suggested_round: int | None
    meeting_url: str | None


# --------------------------------------------------------------------------
# Unified calendar feed
# --------------------------------------------------------------------------


class CalendarFeedEvent(BaseModel):
    """One block on the calendar grid, from either source."""

    id: str
    kind: str  # "interview" | "external"
    person_id: str
    person_name: str
    person_color: str
    person_initials: str
    title: str
    starts_at: datetime
    ends_at: datetime
    timezone: str | None = None
    is_all_day: bool = False
    location: str | None = None
    meeting_url: str | None = None

    # -- interview context (null for plain external events) -----------------
    application_id: str | None = None
    interview_stage_id: str | None = None
    interview_event_id: str | None = None
    calendar_event_id: str | None = None
    company_name: str | None = None
    job_title: str | None = None
    stage_badge: str | None = None
    type_key: str | None = None
    type_label: str | None = None
    type_short_label: str | None = None
    round_number: int | None = None
    stage_status: str | None = None
    stage_outcome: str | None = None

    # -- external context ---------------------------------------------------
    classification: str | None = None
    detection_score: float = 0.0
    is_suggestion: bool = False


class CalendarFeedOut(BaseModel):
    start: datetime
    end: datetime
    events: list[CalendarFeedEvent] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)
    person_ids: list[str] = Field(default_factory=list)
