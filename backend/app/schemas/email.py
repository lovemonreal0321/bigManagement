"""Email + AI schemas.

As with calendar connections, nothing here exposes a credential: no OAuth
token, and no IMAP password (not even the ciphertext).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel

# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------


class EmailAccountOut(ORMModel):
    id: str
    person_id: str
    provider: str
    provider_display_name: str = ""
    address: str
    display_name: str | None
    status: str
    last_used_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    imap_host: str | None = None
    imap_folders: list[str] | None = None
    created_at: datetime

    person_name: str = ""
    person_color: str = ""
    person_initials: str = ""


class ImapAccountCreate(BaseModel):
    """Connect a mailbox with an app-specific password (Yahoo, iCloud, …)."""

    person_id: str
    address: EmailStr
    password: str = Field(min_length=1, max_length=512)
    #: Left blank, these are inferred from the address for known providers.
    imap_host: str | None = None
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    imap_username: str | None = None
    imap_use_ssl: bool = True
    folders: list[str] | None = None


class EmailAccountUpdate(BaseModel):
    display_name: str | None = None
    #: Supply only when rotating the app password.
    password: str | None = Field(default=None, min_length=1, max_length=512)
    imap_host: str | None = None
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    folders: list[str] | None = None


class ImapHostSuggestion(BaseModel):
    host: str | None
    port: int
    folders: list[str]
    known_provider: bool
    hint: str | None = None


class EmailProviderInfo(BaseModel):
    key: str
    display_name: str
    is_configured: bool
    requires_app_password: bool
    missing_settings: list[str] = Field(default_factory=list)
    setup_hint: str | None = None


# --------------------------------------------------------------------------
# Messages + extractions
# --------------------------------------------------------------------------


class EmailMessageOut(ORMModel):
    id: str
    subject: str | None
    from_address: str | None
    from_name: str | None
    sent_at: datetime | None
    match_score: float
    match_reasons: list[str] | None
    body_excerpt: str | None = None


class AiExtractionOut(ORMModel):
    id: str
    person_id: str | None
    calendar_event_id: str | None
    status: str
    confidence: float
    result: dict[str, Any] | None
    reasoning: str | None
    error: str | None
    model: str | None
    tokens_used: int
    message_count: int
    created_application_id: str | None
    created_stage_id: str | None
    linked_existing_application: bool
    undone_at: datetime | None
    created_at: datetime

    # -- denormalised for the review feed ----------------------------------
    person_name: str = ""
    person_color: str = ""
    person_initials: str = ""
    event_title: str | None = None
    event_starts_at: datetime | None = None
    company_name: str | None = None
    job_title: str | None = None
    stage_badge: str | None = None
    is_undoable: bool = False
    messages: list[EmailMessageOut] = Field(default_factory=list)


class EnrichRequest(BaseModel):
    """Run enrichment for specific events, or let the server pick candidates."""

    calendar_event_ids: list[str] = Field(default_factory=list)
    #: Re-run events that were already processed.
    force: bool = False
    limit: int = Field(default=10, ge=1, le=50)


class EnrichSummary(BaseModel):
    processed: int = 0
    applied: int = 0
    suggested: int = 0
    skipped: int = 0
    failed: int = 0
    tokens_used: int = 0
    extractions: list[AiExtractionOut] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class AiStatusOut(BaseModel):
    """What Settings shows about the AI side."""

    enabled: bool
    configured: bool
    model: str
    base_url: str
    auto_create_confidence: float
    email_accounts: int
    setup_hint: str | None = None
