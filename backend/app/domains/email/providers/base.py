"""The provider-agnostic email interface."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from app.models import EmailAccount

#: Matches an address inside "Display Name <a@b.com>" or a bare address.
ADDRESS_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def extract_addresses(value: str | None) -> list[str]:
    if not value:
        return []
    return [match.group(0).lower() for match in ADDRESS_RE.finditer(value)]


def domain_of(address: str | None) -> str | None:
    if not address or "@" not in address:
        return None
    return address.rsplit("@", 1)[-1].strip().lower()


@dataclass
class EmailQuery:
    """What to look for.

    Deliberately narrow: a time window plus the people involved in a specific
    calendar event. There is no "fetch everything" mode — the anchor is always
    an event that already exists.
    """

    #: Any message involving one of these addresses matches.
    participants: list[str] = field(default_factory=list)
    #: ...or any message from one of these domains (the company).
    domains: list[str] = field(default_factory=list)
    after: datetime | None = None
    before: datetime | None = None
    #: Free-text terms (company name, role) used as a secondary signal.
    terms: list[str] = field(default_factory=list)
    limit: int = 25


@dataclass
class FetchedMessage:
    """One message, normalised across providers."""

    provider_message_id: str
    thread_id: str | None = None
    subject: str | None = None
    from_address: str | None = None
    from_name: str | None = None
    to_addresses: list[str] = field(default_factory=list)
    sent_at: datetime | None = None
    body: str | None = None

    @property
    def participants(self) -> list[str]:
        addresses = list(self.to_addresses)
        if self.from_address:
            addresses.append(self.from_address)
        return [a.lower() for a in addresses if a]


class EmailProviderAdapter(ABC):
    """One implementation per mail backend."""

    key: str
    display_name: str

    @abstractmethod
    def is_configured(self, account: EmailAccount) -> bool:
        """Whether this account has everything it needs to connect."""

    @abstractmethod
    def verify(self, account: EmailAccount) -> str:
        """Prove the credentials work. Returns the resolved address.

        Raises `AppError` with a user-facing message on failure.
        """

    @abstractmethod
    def search(self, account: EmailAccount, query: EmailQuery) -> list[FetchedMessage]:
        """Return messages matching the query, newest first."""
