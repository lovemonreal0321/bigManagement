"""Lightweight activity log (spec §33 — deliberately not a full audit system)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.timeutils import utcnow
from app.core.types import GUID, UTCDateTime
from app.models.base import UUIDMixin


class Activity(Base, UUIDMixin):
    """One human-readable line describing something that happened.

    No `updated_at`: activity rows are append-only. Foreign keys use
    `SET NULL` so deleting an application does not erase the record that it
    once existed.
    """

    __tablename__ = "activities"
    __table_args__ = (
        Index("ix_activities_created_at", "created_at"),
        Index("ix_activities_person_created", "person_id", "created_at"),
        Index("ix_activities_application", "application_id"),
    )

    workspace_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    person_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("people.id", ondelete="SET NULL"), nullable=True
    )
    application_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    interview_stage_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("interview_stages.id", ondelete="SET NULL"), nullable=True
    )
    follow_up_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("follow_ups.id", ondelete="SET NULL"), nullable=True
    )

    type: Mapped[str] = mapped_column(String(48), nullable=False)
    #: Pre-rendered sentence, e.g. "John's Amazon interview changed from
    #: Scheduled to Completed". Rendering at write time keeps the feed cheap
    #: to read and stable even if a referenced row is later archived.
    message: Mapped[str] = mapped_column(Text, nullable=False)
    #: Structured extras (from/to values, company name) for richer rendering.
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, nullable=False
    )
