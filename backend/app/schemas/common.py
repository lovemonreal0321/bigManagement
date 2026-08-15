"""Shared response shapes."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    """Base for schemas read directly off ORM objects."""

    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    """Cursor-free offset pagination — enough for lists of this size (spec §56)."""

    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class ErrorResponse(BaseModel):
    error: ErrorBody


class OkResponse(BaseModel):
    ok: bool = True
    message: str | None = None


class CountByKey(BaseModel):
    key: str
    label: str
    count: int
