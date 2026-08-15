"""Job applications and their notes."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.types import GUID, UTCDateTime
from app.enums import (
    ApplicationStatus,
    EmploymentType,
    Priority,
    WorkMode,
)
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.followup import FollowUp
    from app.models.interview import InterviewStage
    from app.models.person import Person


class Application(Base, UUIDMixin, TimestampMixin):
    """One opportunity at one company, owned by exactly one Person (spec §11)."""

    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_person_status", "person_id", "status"),
        Index("ix_applications_status", "status"),
        Index("ix_applications_applied_date", "applied_date"),
        Index("ix_applications_archived_at", "archived_at"),
        Index("ix_applications_company", "company_name"),
    )

    workspace_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    person_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("people.id", ondelete="CASCADE"), nullable=False
    )

    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    job_title: Mapped[str] = mapped_column(String(255), nullable=False)
    job_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    work_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=WorkMode.UNKNOWN.value
    )
    employment_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EmploymentType.UNKNOWN.value
    )

    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    hourly_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    applied_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ApplicationStatus.APPLIED.value
    )
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Priority.MEDIUM.value
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_version_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("resume_versions.id", ondelete="SET NULL"), nullable=True
    )

    #: Denormalised "last time anything happened here", maintained by the
    #: services. Powers the "no activity for N days" rule and the
    #: days-since-activity badge without an aggregate query per card (spec §56).
    last_activity_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    #: Soft delete (spec §36).
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    person: Mapped[Person] = relationship(back_populates="applications")
    stages: Mapped[list[InterviewStage]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="InterviewStage.sequence",
    )
    follow_ups: Mapped[list[FollowUp]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    application_notes: Mapped[list[ApplicationNote]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationNote.created_at.desc()",
    )

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


class ApplicationNote(Base, UUIDMixin, TimestampMixin):
    """A timestamped note. Distinct from `Application.notes`, which is the
    single free-text summary field shown in the header."""

    __tablename__ = "application_notes"

    application_id: Mapped[str] = mapped_column(
        GUID,
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)

    application: Mapped[Application] = relationship(back_populates="application_notes")
