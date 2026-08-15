"""Custom SQLAlchemy column types.

The important one is :class:`UTCDateTime`. SQLite has no real timezone-aware
type, so a naive datetime written to it is ambiguous — exactly what spec §44
forbids. This decorator enforces the invariant at the column boundary:

* on the way **in**, an aware datetime is converted to UTC and stored naive;
  a naive datetime is rejected outright so no caller can smuggle in local time.
* on the way **out**, the stored value is re-tagged as UTC.

Application code therefore only ever sees aware UTC datetimes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CHAR, DateTime, TypeDecorator
from sqlalchemy.engine import Dialect


class UTCDateTime(TypeDecorator):
    """Timezone-aware datetime stored as naive UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):  # pragma: no cover - defensive
            raise TypeError(f"expected datetime, got {type(value)!r}")
        if value.tzinfo is None:
            raise ValueError(
                "naive datetime rejected: attach a timezone before persisting "
                "(see app.core.timeutils.to_utc)"
            )
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class GUID(TypeDecorator):
    """UUID stored as a 36-char string (SQLite has no native UUID type)."""

    impl = CHAR(36)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        text = str(value)
        try:
            # Normalise so a value written with braces or without dashes still
            # matches a canonically stored id.
            return str(uuid.UUID(text))
        except (ValueError, AttributeError, TypeError):
            # Not a UUID at all — most likely a bad id from a stale URL. Pass it
            # through so the query matches nothing and the caller returns a
            # clean 404, rather than raising and turning it into a 500.
            # Genuine bad writes are still caught by the foreign keys.
            return text

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return str(value)
