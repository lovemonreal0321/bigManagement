"""Person schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.timeutils import is_valid_timezone
from app.domains.people.colors import is_valid_color
from app.schemas.common import ORMModel


def _validate_color(value: str | None) -> str | None:
    if value is not None and not is_valid_color(value):
        raise ValueError("Colour must be a hex value like #2563eb")
    return value


def _validate_timezone(value: str | None) -> str | None:
    if value is not None and not is_valid_timezone(value):
        raise ValueError(f"Unknown timezone: {value}")
    return value


class PersonBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    initials: str | None = Field(default=None, max_length=4)
    color: str | None = Field(default=None, max_length=9)
    avatar_url: str | None = None
    email: EmailStr | None = None
    timezone: str | None = Field(default=None, max_length=64)

    _color = field_validator("color")(_validate_color)
    _timezone = field_validator("timezone")(_validate_timezone)


class PersonCreate(PersonBase):
    pass


class PersonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    initials: str | None = Field(default=None, max_length=4)
    color: str | None = Field(default=None, max_length=9)
    avatar_url: str | None = None
    email: EmailStr | None = None
    timezone: str | None = Field(default=None, max_length=64)
    sort_order: int | None = None

    _color = field_validator("color")(_validate_color)
    _timezone = field_validator("timezone")(_validate_timezone)


class PersonOut(ORMModel):
    id: str
    name: str
    display_name: str
    initials: str
    color: str
    avatar_url: str | None
    email: str | None
    timezone: str
    is_active: bool
    archived_at: datetime | None
    sort_order: int
    created_at: datetime
    updated_at: datetime


class PersonWithStats(PersonOut):
    """Person plus the counters the People page shows."""

    application_count: int = 0
    active_application_count: int = 0
    upcoming_interview_count: int = 0
    open_follow_up_count: int = 0
    calendar_connection_count: int = 0


class PersonArchiveCheck(BaseModel):
    """Preflight for deletion: tells the UI whether a hard delete is allowed."""

    can_delete: bool
    application_count: int
    reason: str | None = None
