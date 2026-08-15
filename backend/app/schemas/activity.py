"""Activity log schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.schemas.common import ORMModel


class ActivityOut(ORMModel):
    id: str
    type: str
    message: str
    meta: dict[str, Any] | None = None
    person_id: str | None = None
    application_id: str | None = None
    interview_stage_id: str | None = None
    follow_up_id: str | None = None
    created_at: datetime

    # -- denormalised for rendering ----------------------------------------
    person_name: str = ""
    person_color: str = ""
    person_initials: str = ""
