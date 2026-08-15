"""Email accounts, cached messages, and the audit trail for AI-created records.

Email exists here for exactly one job (chosen deliberately): when the calendar
says an interview is happening, find the messages *about that interview* and
read the details out of them. Mail is never scanned as a general inbox, and no
application is ever discovered from email alone — the calendar is the trigger.
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
from app.enums import ConnectionStatus, EmailProvider, ExtractionStatus
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.person import Person


class EmailAccount(Base, UUIDMixin, TimestampMixin):
    """A mailbox belonging to one Person.

    Two shapes share this table:

    * `gmail` — OAuth, reusing the same Google client as Calendar. No password
      is stored; the refresh token is held like any other OAuth credential.
    * `imap` — host/port/username plus an app-specific password, encrypted at
      rest. This is the only workable route for Yahoo, which no longer grants
      OAuth to third-party apps.
    """

    __tablename__ = "email_accounts"
    __table_args__ = (
        UniqueConstraint(
            "person_id", "provider", "address", name="uq_email_person_provider_address"
        ),
    )

    person_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("people.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The mailbox address, and the identity shown in the UI.
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # -- OAuth (gmail) -----------------------------------------------------
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -- IMAP --------------------------------------------------------------
    imap_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imap_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imap_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Fernet ciphertext — never the password itself (see core/crypto.py).
    imap_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    imap_use_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Mailboxes to search. Defaults to INBOX plus the provider's archive.
    imap_folders: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # -- state -------------------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ConnectionStatus.CONNECTED.value
    )
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    person: Mapped[Person] = relationship()

    @property
    def is_gmail(self) -> bool:
        return self.provider == EmailProvider.GMAIL.value

    @property
    def is_healthy(self) -> bool:
        return self.status == ConnectionStatus.CONNECTED.value


class EmailMessage(Base, UUIDMixin, TimestampMixin):
    """A message that was matched to a calendar event and used for enrichment.

    Only matched candidates are stored, and only the fields needed to show the
    user what the AI read. Bodies are truncated — the point is provenance, not
    building a mail client.
    """

    __tablename__ = "email_messages"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "provider_message_id", name="uq_email_account_message"
        ),
        Index("ix_email_messages_event", "calendar_event_id"),
        Index("ix_email_messages_sent", "sent_at"),
    )

    account_id: Mapped[str] = mapped_column(
        GUID,
        ForeignKey("email_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: What this message was matched to. The calendar event is the anchor.
    calendar_event_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=True
    )
    provider_message_id: Mapped[str] = mapped_column(String(512), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(512), nullable=True)

    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_address: Mapped[str | None] = mapped_column(String(320), nullable=True)
    from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_addresses: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: Plain-text body, truncated. This is what gets sent to the model.
    body_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Why the matcher picked this message, shown in the UI for transparency.
    match_reasons: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class AiExtraction(Base, UUIDMixin, TimestampMixin):
    """One AI enrichment run, and what it did.

    This is what makes "auto-create with undo" honest: every record the model
    creates is traceable back to the event and messages it read, the prompt
    version, the confidence, and the exact rows it produced — so undo can
    remove precisely those and nothing else.
    """

    __tablename__ = "ai_extractions"
    __table_args__ = (
        Index("ix_ai_extractions_status_created", "status", "created_at"),
        UniqueConstraint("calendar_event_id", name="uq_ai_extraction_event"),
    )

    workspace_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    person_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("people.id", ondelete="SET NULL"), nullable=True
    )
    calendar_event_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ExtractionStatus.PENDING.value
    )
    #: 0-1 from the model, used to decide auto-create vs. suggestion.
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: The structured result, kept verbatim for debugging and for the UI diff.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # -- what it created, so undo can be exact -----------------------------
    created_application_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    created_stage_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("interview_stages.id", ondelete="SET NULL"), nullable=True
    )
    #: True when the application already existed and only a stage was added, so
    #: undo removes the stage but leaves the application alone.
    linked_existing_application: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    undone_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    @property
    def is_undoable(self) -> bool:
        return (
            self.undone_at is None
            and self.status == ExtractionStatus.APPLIED.value
            and (self.created_application_id or self.created_stage_id) is not None
        )
