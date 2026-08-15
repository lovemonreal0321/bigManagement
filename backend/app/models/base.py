"""Shared ORM mixins."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutils import utcnow
from app.core.types import GUID, UTCDateTime


def new_uuid() -> str:
    return str(uuid.uuid4())


class UUIDMixin:
    """Primary key as a UUID string (spec §36)."""

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
