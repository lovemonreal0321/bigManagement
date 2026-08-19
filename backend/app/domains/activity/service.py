"""Activity log writer and reader.

Deliberately minimal (spec §33): one pre-rendered sentence per event, plus a
small `meta` blob. No diffing engine, no generic audit trail.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.enums import ActivityType
from app.models import Activity


def log(
    db: Session,
    *,
    workspace_id: str,
    activity_type: ActivityType,
    message: str,
    person_id: str | None = None,
    application_id: str | None = None,
    interview_stage_id: str | None = None,
    follow_up_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> Activity:
    """Append one activity row.

    Does not commit — it joins the caller's transaction so an activity line is
    never written for a change that then rolls back.
    """
    entry = Activity(
        workspace_id=workspace_id,
        person_id=person_id,
        application_id=application_id,
        interview_stage_id=interview_stage_id,
        follow_up_id=follow_up_id,
        type=activity_type.value,
        message=message,
        meta=meta,
    )
    db.add(entry)
    return entry


def list_activities(
    db: Session,
    *,
    workspace_id: str,
    person_ids: list[str] | None = None,
    application_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Activity], int]:
    from sqlalchemy import func

    stmt = select(Activity).where(Activity.workspace_id == workspace_id)
    count_stmt = select(func.count(Activity.id)).where(
        Activity.workspace_id == workspace_id
    )

    if person_ids is not None:
        # Workspace-level entries (person_id NULL) stay visible regardless of
        # the person filter — e.g. a recovery sign-in, or "3 people archived"
        # style bookkeeping. `IN (...)` alone would drop them, because SQL
        # comparisons against NULL are never true.
        clause = or_(
            Activity.person_id.in_(person_ids), Activity.person_id.is_(None)
        )
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    if application_id:
        stmt = stmt.where(Activity.application_id == application_id)
        count_stmt = count_stmt.where(Activity.application_id == application_id)

    total = db.scalar(count_stmt) or 0
    items = list(
        db.scalars(
            stmt.order_by(Activity.created_at.desc()).limit(limit).offset(offset)
        )
    )
    return items, total
