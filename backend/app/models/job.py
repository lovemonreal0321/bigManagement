"""Jobs — the thing the whole search is for.

A job is deliberately not an application with a different status. An
application is an opportunity being pursued; a job is income being earned, with
a start date, a rate and a payday. They answer different questions and outlive
each other: an application can be archived while the job it produced runs for
years, and a job can exist with no application behind it at all.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.types import GUID
from app.enums import (
    DEFAULT_HOURS_PER_WEEK,
    DEFAULT_WEEKS_PER_YEAR,
    JobStatus,
    JobType,
    PayPeriod,
    SalaryType,
)
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.interview import InterviewStage
    from app.models.person import Person


class Job(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_person_status", "person_id", "status"),
        Index("ix_jobs_person_start", "person_id", "start_date"),
    )

    workspace_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    person_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("people.id", ondelete="CASCADE"), nullable=False
    )

    # -- provenance --------------------------------------------------------
    #: Optional links back to where the job came from. `SET NULL` rather than
    #: cascade: archiving the application must never delete the job it won.
    application_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    interview_stage_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("interview_stages.id", ondelete="SET NULL"), nullable=True
    )

    # -- what the job is ---------------------------------------------------
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    job_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=JobType.FULL_TIME.value
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=JobStatus.OFFERED.value
    )
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # -- dates -------------------------------------------------------------
    offered_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    end_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -- money -------------------------------------------------------------
    #: Which figure the user typed. The other is derived from it, but both are
    #: stored so a hand-corrected annual figure is not silently recomputed away.
    salary_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SalaryType.ANNUAL.value
    )
    annual_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    hourly_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    #: The conversion basis, per job — part-time and contract roles are not 40x52.
    hours_per_week: Mapped[float] = mapped_column(
        Float, nullable=False, default=DEFAULT_HOURS_PER_WEEK
    )
    weeks_per_year: Mapped[float] = mapped_column(
        Float, nullable=False, default=DEFAULT_WEEKS_PER_YEAR
    )

    # -- payday ------------------------------------------------------------
    pay_period: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PayPeriod.BIWEEKLY.value
    )
    first_pay_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -- relationships -----------------------------------------------------
    person: Mapped[Person] = relationship(lazy="joined")
    application: Mapped[Application | None] = relationship(lazy="selectin")
    interview_stage: Mapped[InterviewStage | None] = relationship(lazy="selectin")

    @property
    def is_live(self) -> bool:
        """Accepted or being worked — i.e. income, current or imminent."""
        from app.enums import LIVE_JOB_STATUSES

        return self.status in LIVE_JOB_STATUSES
