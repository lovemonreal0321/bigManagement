"""Workspace, user and workspace-level settings."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.types import GUID, UTCDateTime
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.person import Person


class Workspace(Base, UUIDMixin, TimestampMixin):
    """The single tenant everything hangs off.

    Multi-workspace is explicitly out of scope (spec §62) but modelling the row
    now means adding it later is a routing change, not a migration of every
    table.
    """

    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    default_timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="America/New_York"
    )
    #: 0 = Monday, 6 = Sunday.
    week_starts_on: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # -- calendar sync settings (spec §7: "make those configurable") ---------
    sync_window_past_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    sync_window_future_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90
    )
    auto_detect_interviews: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # -- follow-up automation settings (spec §21) ---------------------------
    followup_after_interview_business_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    followup_chain_business_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5
    )
    waiting_for_feedback_threshold_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=7
    )
    no_activity_ghosted_threshold_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=21
    )

    #: "workspace" renders every time in the workspace timezone; "person"
    #: renders each event in its own person's timezone (spec §44).
    display_timezone_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="workspace"
    )

    people: Mapped[list[Person]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    users: Mapped[list[User]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class User(Base, UUIDMixin, TimestampMixin):
    """A login account.

    Distinct from `Person`: a User signs in, a Person is a job seeker being
    tracked. The default deployment has exactly one User and several People.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)

    workspace_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    username: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    workspace: Mapped[Workspace] = relationship(back_populates="users")
