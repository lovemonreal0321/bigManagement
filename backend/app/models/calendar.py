"""Calendar connections, calendars and events.

Provider-independent by design (spec §6): nothing outside
`domains/calendar/providers/` knows whether a row came from Google or
Microsoft. Adding a third provider means adding an adapter, not touching this
schema.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
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
    CalendarProvider,
    ConnectionStatus,
    EventClassification,
    EventSource,
    EventStatus,
)
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.interview import InterviewEvent
    from app.models.person import Person


class CalendarConnection(Base, UUIDMixin, TimestampMixin):
    """One OAuth-connected calendar account belonging to one Person.

    A Person may have zero, one, or several connections (spec §6). OAuth tokens
    live here and are never serialised to any API response — see
    `schemas/calendar.py`, which has no token fields at all.
    """

    __tablename__ = "calendar_connections"
    __table_args__ = (
        UniqueConstraint(
            "person_id",
            "provider",
            "provider_account_id",
            name="uq_connection_person_provider_account",
        ),
    )

    person_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("people.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Stable provider-side account identifier (Google `sub`, Graph `id`).
    provider_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    account_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # -- secrets -----------------------------------------------------------
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -- sync state --------------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ConnectionStatus.CONNECTED.value
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_error_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    #: Per-connection overrides; fall back to the workspace values when null.
    sync_window_past_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sync_window_future_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    person: Mapped[Person] = relationship(back_populates="calendar_connections")
    calendars: Mapped[list[ExternalCalendar]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )

    @property
    def is_google(self) -> bool:
        return self.provider == CalendarProvider.GOOGLE.value

    @property
    def is_healthy(self) -> bool:
        return self.status == ConnectionStatus.CONNECTED.value


class ExternalCalendar(Base, UUIDMixin, TimestampMixin):
    """One calendar inside a connected account (a Google calendar / Graph
    calendar). Only `is_selected` calendars are synced."""

    __tablename__ = "external_calendars"
    __table_args__ = (
        UniqueConstraint(
            "connection_id", "provider_calendar_id", name="uq_calendar_connection_ext_id"
        ),
    )

    connection_id: Mapped[str] = mapped_column(
        GUID,
        ForeignKey("calendar_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_calendar_id: Mapped[str] = mapped_column(String(512), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_write: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Provider incremental-sync cursor (Google syncToken / Graph deltaLink).
    sync_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    connection: Mapped[CalendarConnection] = relationship(back_populates="calendars")
    events: Mapped[list[CalendarEvent]] = relationship(
        back_populates="external_calendar", cascade="all, delete-orphan"
    )


class CalendarEvent(Base, UUIDMixin, TimestampMixin):
    """A calendar event — imported from a provider, or created by this app.

    This is the source of truth for *when* something happens. An
    `InterviewEvent` points at one of these rows; when the provider moves an
    event, the linked interview time moves with it.
    """

    __tablename__ = "calendar_events"
    __table_args__ = (
        # Spec §36: the provider event id must be unique within its calendar.
        # This is what makes re-running a sync idempotent.
        UniqueConstraint(
            "external_calendar_id",
            "provider_event_id",
            name="uq_event_calendar_provider_id",
        ),
        Index("ix_calendar_events_person_start", "person_id", "starts_at"),
        Index("ix_calendar_events_classification", "classification"),
        Index("ix_calendar_events_starts_at", "starts_at"),
    )

    person_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("people.id", ondelete="CASCADE"), nullable=False
    )
    #: Null for app-created events that have not been pushed to a provider.
    external_calendar_id: Mapped[str | None] = mapped_column(
        GUID,
        ForeignKey("external_calendars.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    connection_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("calendar_connections.id", ondelete="CASCADE"), nullable=True
    )
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    #: Cross-calendar identity, used to spot the same meeting appearing in two
    #: connected accounts (spec §7: "avoid duplicate events").
    ical_uid: Mapped[str | None] = mapped_column(String(1024), nullable=True, index=True)
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)

    title: Mapped[str] = mapped_column(String(1024), nullable=False, default="(no title)")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    meeting_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    organizer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    organizer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attendees: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    starts_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    #: The provider's original timezone is preserved verbatim (spec §44) so an
    #: event can be shown in the timezone it was actually booked in.
    start_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    end_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: One occurrence of a repeating series, per the provider.
    is_recurring: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EventStatus.CONFIRMED.value
    )
    classification: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=EventClassification.UNCLASSIFIED.value,
    )
    #: True once a human has classified it — stops auto-detection from
    #: overwriting a deliberate decision on the next sync.
    classification_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EventSource.EXTERNAL_PROVIDER.value
    )

    # -- interview detection (suggestion only — spec §8) --------------------
    detection_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    detection_reasons: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    detection_dismissed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: Soft delete: a cancelled/removed provider event keeps its row so linked
    #: interview history survives (spec §36).
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    person: Mapped[Person] = relationship(back_populates="calendar_events")
    external_calendar: Mapped[ExternalCalendar | None] = relationship(
        back_populates="events"
    )
    interview_event: Mapped[InterviewEvent | None] = relationship(
        back_populates="calendar_event", uselist=False
    )

    @property
    def is_cancelled(self) -> bool:
        return self.status == EventStatus.CANCELLED.value or self.deleted_at is not None

    @property
    def is_app_created(self) -> bool:
        return self.source == EventSource.APP_CREATED.value
