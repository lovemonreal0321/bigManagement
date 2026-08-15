"""Person — a job seeker tracked in the workspace."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.types import GUID, UTCDateTime
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.calendar import CalendarConnection, CalendarEvent
    from app.models.followup import FollowUp
    from app.models.workspace import Workspace


class Person(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "people"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_people_workspace_name"),
    )

    workspace_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    initials: Mapped[str] = mapped_column(String(4), nullable=False)
    #: Hex colour, e.g. "#2563eb". Unique per person and used consistently
    #: across calendar, cards, charts and badges (spec §5).
    color: Mapped[str] = mapped_column(String(9), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="America/New_York"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Soft delete. People are never hard-deleted while history exists (spec §5).
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    workspace: Mapped[Workspace] = relationship(back_populates="people")
    applications: Mapped[list[Application]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    calendar_connections: Mapped[list[CalendarConnection]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    calendar_events: Mapped[list[CalendarEvent]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    follow_ups: Mapped[list[FollowUp]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


class ResumeVersion(Base, UUIDMixin, TimestampMixin):
    """Optional: a named resume an application was submitted with (spec §34)."""

    __tablename__ = "resume_versions"

    person_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("people.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_url: Mapped[str | None] = mapped_column(Text, nullable=True)
