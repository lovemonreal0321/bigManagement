"""Auth request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.enums import UserRole
from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class UserOut(ORMModel):
    id: str
    username: str
    display_name: str
    email: str | None = None
    workspace_id: str
    role: UserRole
    is_active: bool = True
    must_change_password: bool = False
    last_login_at: datetime | None = None
    #: Profiles this user may edit. Empty for an admin, who may edit everyone —
    #: read `is_admin` first rather than treating the empty list as "nothing".
    assigned_person_ids: list[str] = Field(default_factory=list)

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=6, max_length=200)


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=6, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    role: UserRole = UserRole.USER
    person_ids: list[str] = Field(default_factory=list)

    @field_validator("username")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return value.strip().lower()


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    role: UserRole | None = None
    is_active: bool | None = None


class SetPasswordRequest(BaseModel):
    """An admin setting someone else's password — no current password needed."""

    password: str = Field(min_length=6, max_length=200)


class AssignPeopleRequest(BaseModel):
    person_ids: list[str] = Field(default_factory=list)
