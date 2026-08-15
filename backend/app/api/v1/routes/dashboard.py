"""Dashboard and activity endpoints (spec §22, §23, §33)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from app.core.deps import CurrentWorkspace, DbSession, SelectedPeople
from app.core.timeutils import local_date, utcnow
from app.domains.activity import service as activity_service
from app.domains.analytics.periods import resolve_period
from app.domains.dashboard import service as dashboard_service
from app.models import Person
from app.schemas.activity import ActivityOut
from app.schemas.common import Page
from app.schemas.dashboard import AttentionItem, DashboardOut

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    period: str = Query("last_30_days"),
    start: date | None = None,
    end: date | None = None,
) -> DashboardOut:
    today = local_date(utcnow(), workspace.default_timezone)
    resolved = resolve_period(
        period,
        today=today,
        start=start,
        end=end,
        week_starts_on=workspace.week_starts_on,
    )
    return dashboard_service.build_dashboard(db, workspace, scope.people, resolved)


@router.get("/dashboard/needs-attention", response_model=list[AttentionItem])
def get_needs_attention(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    limit: int = Query(12, ge=1, le=50),
) -> list[AttentionItem]:
    return dashboard_service.build_needs_attention(
        db, workspace, scope.people, limit=limit
    )


@router.get("/activity", response_model=Page[ActivityOut])
def list_activity(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    application_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[ActivityOut]:
    entries, total = activity_service.list_activities(
        db,
        workspace_id=workspace.id,
        person_ids=scope.ids,
        application_id=application_id,
        limit=limit,
        offset=offset,
    )
    people = {p.id: p for p in db.query(Person).filter(Person.id.in_(scope.ids)).all()}
    items = []
    for entry in entries:
        out = ActivityOut.model_validate(entry)
        person = people.get(entry.person_id or "")
        if person is not None:
            out.person_name = person.display_name
            out.person_color = person.color
            out.person_initials = person.initials
        items.append(out)
    return Page[ActivityOut](items=items, total=total, limit=limit, offset=offset)
