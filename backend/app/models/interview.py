"""Interview stages and the calendar events that make them up.

The key modelling decision (spec §16): a *stage* is a step in the hiring
process; an *event* is a block of time. A "final loop" is one stage with four
events. Nothing here assumes 1:1.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.types import GUID, UTCDateTime
from app.enums import (
    EventSource,
    InterviewOutcome,
    InterviewStatus,
    InterviewTypeKey,
    SyncState,
)
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.calendar import CalendarEvent
    from app.models.followup import FollowUp


class InterviewType(Base, UUIDMixin, TimestampMixin):
    """Registry of interview types — the built-ins plus any custom ones the
    user adds (spec §14)."""

    __tablename__ = "interview_types"
    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_interview_type_workspace_key"),
    )

    workspace_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Compact form for calendar chips and pipeline cards.
    short_label: Mapped[str] = mapped_column(String(32), nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Custom types opt into the technical pass-rate metric explicitly.
    counts_as_technical: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    counts_as_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Screening rounds are excluded from the "reached a real interview"
    #: conversion metric — see domains/analytics/formulas.py.
    counts_as_screening: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )


class InterviewStage(Base, UUIDMixin, TimestampMixin):
    """One step of one company's hiring process."""

    __tablename__ = "interview_stages"
    __table_args__ = (
        Index("ix_stages_application_sequence", "application_id", "sequence"),
        Index("ix_stages_outcome", "outcome"),
        Index("ix_stages_status", "status"),
        Index("ix_stages_scheduled_start", "scheduled_start"),
        Index("ix_stages_type", "type_key"),
    )

    application_id: Mapped[str] = mapped_column(
        GUID,
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Optional because plenty of processes are not numbered (spec §14).
    round_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Always set. Defines display order in the journey timeline.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type_key: Mapped[str] = mapped_column(
        String(64), nullable=False, default=InterviewTypeKey.OTHER.value
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=InterviewStatus.PLANNED.value
    )
    outcome: Mapped[str] = mapped_column(
        String(32), nullable=False, default=InterviewOutcome.PENDING.value
    )

    #: Mirrors the earliest/latest of this stage's events. Denormalised so
    #: calendars and "upcoming" lists can sort without joining (spec §56).
    scheduled_start: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: When the verdict landed — used for "days waiting" and analytics periods.
    result_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    application: Mapped[Application] = relationship(back_populates="stages")
    events: Mapped[list[InterviewEvent]] = relationship(
        back_populates="stage",
        cascade="all, delete-orphan",
        order_by="InterviewEvent.starts_at",
    )
    follow_ups: Mapped[list[FollowUp]] = relationship(back_populates="stage")


class InterviewEvent(Base, UUIDMixin, TimestampMixin):
    """A single time block belonging to an interview stage.

    Optionally backed by a `CalendarEvent`. When it is, the calendar row owns
    the timing and this row mirrors it on each sync.
    """

    __tablename__ = "interview_events"
    __table_args__ = (
        # One calendar event backs at most one interview slot.
        UniqueConstraint("calendar_event_id", name="uq_interview_event_calendar_event"),
        Index("ix_interview_events_stage_start", "interview_stage_id", "starts_at"),
        Index("ix_interview_events_starts_at", "starts_at"),
    )

    interview_stage_id: Mapped[str] = mapped_column(
        GUID,
        ForeignKey("interview_stages.id", ondelete="CASCADE"),
        nullable=False,
    )
    calendar_event_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("calendar_events.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    #: A loop slot can carry its own type ("System Design" inside a "Final
    #: Loop" stage). Falls back to the stage's type when null.
    type_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    meeting_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    interviewer_names: Mapped[str | None] = mapped_column(Text, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Where this slot came from, which decides write-back behaviour (spec §48).
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EventSource.APP_CREATED.value
    )
    sync_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SyncState.LOCAL_ONLY.value
    )
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    stage: Mapped[InterviewStage] = relationship(back_populates="events")
    calendar_event: Mapped[CalendarEvent | None] = relationship(
        back_populates="interview_event"
    )
