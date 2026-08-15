"""Follow-ups — the "what needs my attention" core of the product (spec §19)."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.types import GUID, UTCDateTime
from app.enums import FollowUpRule, FollowUpStatus, Priority
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.interview import InterviewStage
    from app.models.person import Person


class FollowUp(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "follow_ups"
    __table_args__ = (
        # `person_id` needs no index of its own: SQLite can use the leading
        # column of a composite index. Same reasoning throughout the schema.
        Index("ix_followups_person_due", "person_id", "due_date"),
        Index("ix_followups_status_due", "status", "due_date"),
        Index("ix_followups_due_date", "due_date"),
    )

    person_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("people.id", ondelete="CASCADE"), nullable=False
    )
    application_id: Mapped[str] = mapped_column(
        GUID,
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    interview_stage_id: Mapped[str | None] = mapped_column(
        GUID,
        ForeignKey("interview_stages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Date-only, interpreted in the person's timezone when deciding
    #: overdue/due-today (spec §44).
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_time: Mapped[time | None] = mapped_column(Time, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=FollowUpStatus.OPEN.value
    )
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Priority.MEDIUM.value
    )
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: While set and in the future, the item is hidden from the due lists.
    snoozed_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: True when a rule proposed it rather than a human typing it.
    auto_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Which rule created it — also the dedupe key that stops the same rule
    #: firing twice for the same stage (spec §20: no runaway auto-tasks).
    rule_key: Mapped[str] = mapped_column(
        String(32), nullable=False, default=FollowUpRule.MANUAL.value
    )

    person: Mapped[Person] = relationship(back_populates="follow_ups")
    application: Mapped[Application] = relationship(back_populates="follow_ups")
    stage: Mapped[InterviewStage | None] = relationship(back_populates="follow_ups")

    @property
    def is_open(self) -> bool:
        return self.status in (FollowUpStatus.OPEN.value, FollowUpStatus.SNOOZED.value)
