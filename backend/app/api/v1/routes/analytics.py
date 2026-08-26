"""Analytics endpoints (spec §25-§30, §55)."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Query

from app.core import permissions
from app.core.deps import (
    CurrentUser,
    CurrentWorkspace,
    DbSession,
    SelectedPeople,
)
from app.core.timeutils import local_date, start_of_week, utcnow
from app.domains.analytics import service as analytics_service
from app.domains.analytics.periods import PERIOD_LABELS, resolve_period
from app.schemas.analytics import AnalyticsOut, WorkloadOut

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/periods")
def list_periods() -> list[dict[str, str]]:
    return [{"key": key, "label": label} for key, label in PERIOD_LABELS.items()]


@router.get("", response_model=AnalyticsOut)
def get_analytics(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    user: CurrentUser,
    period: str = Query("last_30_days"),
    start: date | None = None,
    end: date | None = None,
    include_trend: bool = True,
) -> AnalyticsOut:
    today = local_date(utcnow(), workspace.default_timezone)
    resolved = resolve_period(
        period,
        today=today,
        start=start,
        end=end,
        week_starts_on=workspace.week_starts_on,
    )
    result = analytics_service.compute_analytics(
        db,
        workspace,
        scope.people,
        resolved,
        include_comparison=len(scope.people) > 1,
        include_trend=include_trend,
    )
    # The jobs block carries pay, so it follows the same rule as the Jobs
    # section rather than riding in on the analytics page.
    if not permissions.can_view_jobs(user):
        result.jobs = None
    return result


@router.get("/formulas")
def get_formulas() -> dict[str, str]:
    """The metric definitions, served straight from the source docstring.

    Exposing this means the UI can show exactly how a number was produced
    rather than asking the user to trust it (spec §54).
    """
    from app.domains.analytics import formulas

    return {
        "documentation": formulas.__doc__ or "",
        "min_meaningful_denominator": str(formulas.MIN_MEANINGFUL_DENOMINATOR),
    }


@router.get("/workload", response_model=WorkloadOut)
def get_workload(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    start: date | None = None,
    end: date | None = None,
    heavy_threshold: int = Query(3, ge=1, le=20),
) -> WorkloadOut:
    """Interview load per person, heavy days and same-person conflicts (spec §30)."""
    today = local_date(utcnow(), workspace.default_timezone)
    if start is None:
        start = start_of_week(today, workspace.week_starts_on)
    if end is None:
        end = start + timedelta(days=6)
    return analytics_service.compute_workload(
        db,
        workspace,
        scope.people,
        start=start,
        end=end,
        heavy_threshold=heavy_threshold,
    )
