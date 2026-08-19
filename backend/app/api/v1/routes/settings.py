"""Workspace settings endpoints (spec §44, §45, §7)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from app.core.deps import AdminUser, CurrentWorkspace, DbSession
from app.core.timeutils import is_valid_timezone
from app.schemas.common import ORMModel

router = APIRouter(prefix="/settings", tags=["settings"])


class WorkspaceSettingsOut(ORMModel):
    id: str
    name: str
    default_timezone: str
    week_starts_on: int
    display_timezone_mode: str
    sync_window_past_days: int
    sync_window_future_days: int
    auto_detect_interviews: bool
    followup_after_interview_business_days: int
    followup_chain_business_days: int
    waiting_for_feedback_threshold_days: int
    no_activity_ghosted_threshold_days: int


class WorkspaceSettingsUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    default_timezone: str | None = Field(default=None, max_length=64)
    week_starts_on: int | None = Field(default=None, ge=0, le=6)
    display_timezone_mode: str | None = None
    sync_window_past_days: int | None = Field(default=None, ge=1, le=3650)
    sync_window_future_days: int | None = Field(default=None, ge=1, le=3650)
    auto_detect_interviews: bool | None = None
    followup_after_interview_business_days: int | None = Field(
        default=None, ge=0, le=60
    )
    followup_chain_business_days: int | None = Field(default=None, ge=0, le=60)
    waiting_for_feedback_threshold_days: int | None = Field(default=None, ge=1, le=365)
    no_activity_ghosted_threshold_days: int | None = Field(default=None, ge=1, le=365)

    @field_validator("default_timezone")
    @classmethod
    def _check_tz(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_timezone(value):
            raise ValueError(f"Unknown timezone: {value}")
        return value

    @field_validator("display_timezone_mode")
    @classmethod
    def _check_mode(cls, value: str | None) -> str | None:
        if value is not None and value not in ("workspace", "person"):
            raise ValueError('Display timezone mode must be "workspace" or "person"')
        return value


@router.get("", response_model=WorkspaceSettingsOut)
def get_settings(workspace: CurrentWorkspace) -> WorkspaceSettingsOut:
    return WorkspaceSettingsOut.model_validate(workspace)


@router.patch("", response_model=WorkspaceSettingsOut)
def update_settings(
    payload: WorkspaceSettingsUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
    admin: AdminUser,
) -> WorkspaceSettingsOut:
    """Workspace-wide settings — sync windows, thresholds, default timezone.

    These affect every person, so they are administrator-only.
    """
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(workspace, key, value)
    db.commit()
    return WorkspaceSettingsOut.model_validate(workspace)


@router.get("/timezones", response_model=list[str])
def list_timezones() -> list[str]:
    """Common timezones for the picker.

    The full IANA list is ~600 entries, most of which are aliases nobody
    wants to scroll past.
    """
    import zoneinfo

    common_prefixes = (
        "America/",
        "Europe/",
        "Asia/",
        "Australia/",
        "Africa/",
        "Pacific/",
    )
    zones = sorted(
        z
        for z in zoneinfo.available_timezones()
        if z.startswith(common_prefixes) and "/" in z
    )
    return ["UTC", *zones]
