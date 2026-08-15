"""The provider-agnostic calendar interface.

Everything above this layer speaks in these dataclasses. Adding a third
provider means implementing `CalendarProviderAdapter` and registering it —
no schema change, no service change (spec §6).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.enums import EventStatus

#: Meeting links we can recognise inside a description or location.
MEETING_URL_RE = re.compile(
    r"https?://(?:[\w-]+\.)*(?:zoom\.us|meet\.google\.com|teams\.microsoft\.com|"
    r"teams\.live\.com|webex\.com|whereby\.com|chime\.aws|bluejeans\.com|"
    r"gotomeeting\.com|around\.co|hopin\.com|riverside\.fm)/[^\s<>\"')]+",
    re.IGNORECASE,
)


def extract_meeting_url(*sources: str | None) -> str | None:
    for source in sources:
        if not source:
            continue
        match = MEETING_URL_RE.search(source)
        if match:
            return match.group(0).rstrip(".,;)")
    return None


@dataclass
class ProviderTokens:
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scope: str | None = None


@dataclass
class ProviderAccount:
    account_id: str
    email: str | None = None
    name: str | None = None


@dataclass
class ProviderCalendar:
    id: str
    name: str
    description: str | None = None
    timezone: str | None = None
    color: str | None = None
    is_primary: bool = False
    can_write: bool = True


@dataclass
class NormalizedEvent:
    """A provider event, flattened into the shape this app stores.

    `starts_at` / `ends_at` are always timezone-aware UTC. `start_timezone`
    keeps the provider's original zone so the UI can show an event in the
    timezone it was actually booked in (spec §44).
    """

    provider_event_id: str
    title: str
    starts_at: datetime
    ends_at: datetime
    ical_uid: str | None = None
    etag: str | None = None
    description: str | None = None
    location: str | None = None
    meeting_url: str | None = None
    organizer_email: str | None = None
    organizer_name: str | None = None
    attendees: list[dict[str, Any]] = field(default_factory=list)
    start_timezone: str | None = None
    end_timezone: str | None = None
    is_all_day: bool = False
    status: EventStatus = EventStatus.CONFIRMED
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class EventPage:
    """One page of sync results."""

    events: list[NormalizedEvent] = field(default_factory=list)
    #: Provider ids removed/cancelled since the last sync token.
    deleted_event_ids: list[str] = field(default_factory=list)
    #: Cursor to pass back next time for an incremental sync.
    next_sync_token: str | None = None


@dataclass
class EventDraft:
    """An event this app wants to create or update on a provider."""

    title: str
    starts_at: datetime
    ends_at: datetime
    description: str | None = None
    location: str | None = None
    timezone: str | None = None


class CalendarProviderAdapter(ABC):
    """One implementation per calendar provider."""

    key: str
    display_name: str
    #: OAuth scopes requested at connect time.
    scopes: list[str]

    # -- configuration -----------------------------------------------------

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """True when the server has client credentials for this provider.

        The app is fully usable with this False — connect buttons simply
        explain what is missing (spec §69).
        """

    @abstractmethod
    def missing_settings(self) -> list[str]:
        """Names of the env vars that still need filling in."""

    # -- OAuth -------------------------------------------------------------

    @abstractmethod
    def authorization_url(self, *, state: str, redirect_uri: str) -> str: ...

    @abstractmethod
    def exchange_code(
        self, *, code: str, redirect_uri: str
    ) -> tuple[ProviderTokens, ProviderAccount]: ...

    @abstractmethod
    def refresh_tokens(self, refresh_token: str) -> ProviderTokens: ...

    # -- calendars ---------------------------------------------------------

    @abstractmethod
    def list_calendars(self, access_token: str) -> list[ProviderCalendar]: ...

    # -- events ------------------------------------------------------------

    @abstractmethod
    def list_events(
        self,
        access_token: str,
        *,
        calendar_id: str,
        start: datetime,
        end: datetime,
        sync_token: str | None = None,
    ) -> EventPage: ...

    @abstractmethod
    def create_event(
        self, access_token: str, *, calendar_id: str, draft: EventDraft
    ) -> NormalizedEvent: ...

    @abstractmethod
    def update_event(
        self,
        access_token: str,
        *,
        calendar_id: str,
        provider_event_id: str,
        draft: EventDraft,
    ) -> NormalizedEvent: ...

    @abstractmethod
    def delete_event(
        self, access_token: str, *, calendar_id: str, provider_event_id: str
    ) -> None: ...
