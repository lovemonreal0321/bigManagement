"""Email provider adapters.

Same shape as the calendar package: one interface, one adapter per backend, and
nothing above this layer knows which is in use.
"""

from __future__ import annotations

from app.core.errors import ValidationError
from app.domains.email.providers.base import (
    EmailProviderAdapter,
    EmailQuery,
    FetchedMessage,
)
from app.domains.email.providers.gmail import GmailAdapter
from app.domains.email.providers.imap import ImapAdapter
from app.domains.email.providers.microsoft import OutlookAdapter
from app.enums import EmailProvider

_ADAPTERS: dict[str, EmailProviderAdapter] = {
    EmailProvider.GMAIL.value: GmailAdapter(),
    EmailProvider.MICROSOFT.value: OutlookAdapter(),
    EmailProvider.IMAP.value: ImapAdapter(),
}


def get_email_adapter(provider: str) -> EmailProviderAdapter:
    adapter = _ADAPTERS.get(provider)
    if adapter is None:
        raise ValidationError(
            f"Unsupported email provider: {provider}", code="unknown_email_provider"
        )
    return adapter


__all__ = [
    "EmailProviderAdapter",
    "EmailQuery",
    "FetchedMessage",
    "get_email_adapter",
]
