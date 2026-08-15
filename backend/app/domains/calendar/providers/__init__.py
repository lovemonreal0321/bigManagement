"""Calendar provider adapters.

`get_adapter(provider)` is the only thing the rest of the codebase uses; no
caller outside this package knows whether it is talking to Google or Microsoft
(spec §6).
"""

from __future__ import annotations

from app.core.errors import ValidationError
from app.domains.calendar.providers.base import CalendarProviderAdapter
from app.domains.calendar.providers.google import GoogleCalendarAdapter
from app.domains.calendar.providers.microsoft import MicrosoftCalendarAdapter
from app.enums import CalendarProvider

_ADAPTERS: dict[str, CalendarProviderAdapter] = {
    CalendarProvider.GOOGLE.value: GoogleCalendarAdapter(),
    CalendarProvider.MICROSOFT.value: MicrosoftCalendarAdapter(),
}


def get_adapter(provider: str) -> CalendarProviderAdapter:
    adapter = _ADAPTERS.get(provider)
    if adapter is None:
        raise ValidationError(
            f"Unsupported calendar provider: {provider}", code="unknown_provider"
        )
    return adapter


def available_providers() -> list[CalendarProviderAdapter]:
    return list(_ADAPTERS.values())


__all__ = ["CalendarProviderAdapter", "available_providers", "get_adapter"]
