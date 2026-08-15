"""Dashboard assembly (spec §22, §23).

One endpoint builds the whole page. That is deliberate: the dashboard is the
screen the user opens every day, and eight separate round-trips would make it
feel slow for no benefit (spec §56, §63).
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.timeutils import (
    day_bounds,
    local_date,
    range_bounds,
    start_of_week,
    utcnow,
)
from app.domains.activity import service as activity_service
from app.domains.analytics.periods import Period
from app.domains.applications.service import ApplicationFilters, build_pipeline
from app.domains.calendar import service as calendar_service
from app.domains.followups import rules as followup_rules
from app.domains.followups.status import compute_state, describe
from app.domains.interviews.service import upcoming_interviews
from app.domains.interviews.types import load_registry, stage_badge
from app.enums import (
    ACTIVE_STATUSES,
    OFFER_STATUSES,
    ApplicationStatus,
    FollowUpComputedStatus,
    FollowUpStatus,
    InterviewOutcome,
    InterviewStatus,
)
from app.models import (
    Application,
    FollowUp,
    InterviewEvent,
    InterviewStage,
    Person,
    Workspace,
)
from app.schemas.activity import ActivityOut
from app.schemas.dashboard import AttentionItem, DashboardOut, MetricCard
from app.schemas.interview import UpcomingInterview

#: How many attention rows to return. More than this stops being a panel.
ATTENTION_LIMIT = 12


def build_dashboard(
    db: Session,
    workspace: Workspace,
    people: list[Person],
    period: Period,
) -> DashboardOut:
    person_ids = [p.id for p in people]
    result = DashboardOut(person_ids=person_ids, period_key=period.key)
    if not person_ids:
        result.metrics = _empty_metrics()
        return result

    registry = load_registry(db, workspace.id)
    now = utcnow()
    tz = workspace.default_timezone
    today = local_date(now, tz)

    result.metrics = _metrics(db, workspace, person_ids, today, tz)
    result.upcoming_interviews = upcoming_interviews(
        db, workspace, person_ids, start=now, limit=10, registry=registry
    )
    result.awaiting_outcome = _awaiting_outcome(db, workspace, person_ids, registry)
    result.needs_attention = build_needs_attention(db, workspace, people, today=today)

    pipeline = build_pipeline(
        db, workspace, ApplicationFilters(person_ids=person_ids)
    )
    result.pipeline = pipeline.columns

    from app.domains.analytics.service import compute_analytics

    analytics = compute_analytics(
        db,
        workspace,
        people,
        period,
        registry=registry,
        include_comparison=True,
        include_trend=False,
    )
    if analytics.comparison:
        result.performance = analytics.comparison
    elif people:
        # A single selected person still deserves a performance row.
        single = compute_analytics(
            db,
            workspace,
            people,
            period,
            registry=registry,
            include_comparison=False,
            include_trend=False,
        )
        from app.schemas.analytics import PersonComparisonRow

        person = people[0]
        result.performance = [
            PersonComparisonRow(
                person_id=person.id,
                person_name=person.display_name,
                person_color=person.color,
                person_initials=person.initials,
                applications=single.volume.applications,
                interviews_held=single.volume.interviews_held,
                interview_stages=single.volume.interview_stages,
                pass_rate=single.conversions.interview_pass_rate,
                final_rounds=single.volume.final_rounds,
                offers=single.volume.offers,
                accepted=single.volume.accepted,
            )
        ]

    activities, _ = activity_service.list_activities(
        db, workspace_id=workspace.id, person_ids=person_ids, limit=12
    )
    people_by_id = {p.id: p for p in people}
    for entry in activities:
        out = ActivityOut.model_validate(entry)
        person = people_by_id.get(entry.person_id or "")
        if person is not None:
            out.person_name = person.display_name
            out.person_color = person.color
            out.person_initials = person.initials
        result.recent_activity.append(out)

    result.follow_up_suggestions = followup_rules.collect_suggestions(
        db, workspace, person_ids, limit=5
    )
    result.interview_suggestions = calendar_service.list_suggestions(
        db, workspace, person_ids, limit=5
    )
    return result


# --------------------------------------------------------------------------
# Metric cards
# --------------------------------------------------------------------------


def _empty_metrics() -> list[MetricCard]:
    return [
        MetricCard(key=key, label=label, value=0)
        for key, label in (
            ("active_applications", "Active Applications"),
            ("interviews_this_week", "Interviews This Week"),
            ("interviews_today", "Interviews Today"),
            ("waiting_for_feedback", "Waiting for Feedback"),
            ("follow_ups_due", "Follow-Ups Due"),
            ("final_rounds", "Final Rounds"),
            ("offers", "Offers"),
        )
    ]


def _metrics(
    db: Session,
    workspace: Workspace,
    person_ids: list[str],
    today: date,
    tz: str | None,
) -> list[MetricCard]:
    active = (
        db.scalar(
            select(func.count(Application.id)).where(
                Application.person_id.in_(person_ids),
                Application.archived_at.is_(None),
                Application.status.in_([s.value for s in ACTIVE_STATUSES]),
            )
        )
        or 0
    )

    week_start = start_of_week(today, workspace.week_starts_on)
    week_from, week_to = range_bounds(week_start, week_start + timedelta(days=6), tz)
    day_from, day_to = day_bounds(today, tz)

    def interview_count(start, end) -> int:
        return (
            db.scalar(
                select(func.count(func.distinct(InterviewEvent.id)))
                .select_from(InterviewEvent)
                .join(
                    InterviewStage,
                    InterviewStage.id == InterviewEvent.interview_stage_id,
                )
                .join(Application, Application.id == InterviewStage.application_id)
                .where(
                    Application.person_id.in_(person_ids),
                    Application.archived_at.is_(None),
                    InterviewStage.status.in_(
                        [
                            InterviewStatus.SCHEDULED.value,
                            InterviewStatus.COMPLETED.value,
                        ]
                    ),
                    InterviewEvent.starts_at >= start,
                    InterviewEvent.starts_at < end,
                )
            )
            or 0
        )

    waiting = (
        db.scalar(
            select(func.count(func.distinct(InterviewStage.id)))
            .select_from(InterviewStage)
            .join(Application, Application.id == InterviewStage.application_id)
            .where(
                Application.person_id.in_(person_ids),
                Application.archived_at.is_(None),
                InterviewStage.outcome == InterviewOutcome.WAITING.value,
            )
        )
        or 0
    )

    follow_ups_due = 0
    for follow_up in db.scalars(
        select(FollowUp).where(
            FollowUp.person_id.in_(person_ids),
            FollowUp.status.in_([FollowUpStatus.OPEN.value, FollowUpStatus.SNOOZED.value]),
        )
    ):
        state = compute_state(
            stored_status=follow_up.status,
            due_date=follow_up.due_date,
            today=today,
            snoozed_until=follow_up.snoozed_until,
        )
        if state.status in (
            FollowUpComputedStatus.OVERDUE,
            FollowUpComputedStatus.DUE_TODAY,
        ):
            follow_ups_due += 1

    finals = (
        db.scalar(
            select(func.count(Application.id)).where(
                Application.person_id.in_(person_ids),
                Application.archived_at.is_(None),
                Application.status == ApplicationStatus.FINAL_ROUND.value,
            )
        )
        or 0
    )
    offers = (
        db.scalar(
            select(func.count(Application.id)).where(
                Application.person_id.in_(person_ids),
                Application.archived_at.is_(None),
                Application.status.in_([s.value for s in OFFER_STATUSES]),
            )
        )
        or 0
    )

    return [
        MetricCard(
            key="active_applications",
            label="Active Applications",
            value=active,
            href="/applications",
        ),
        MetricCard(
            key="interviews_this_week",
            label="Interviews This Week",
            value=interview_count(week_from, week_to),
            href="/calendar",
        ),
        MetricCard(
            key="interviews_today",
            label="Interviews Today",
            value=interview_count(day_from, day_to),
            href="/calendar",
        ),
        MetricCard(
            key="waiting_for_feedback",
            label="Waiting for Feedback",
            value=waiting,
            href="/applications?outcome=waiting",
        ),
        MetricCard(
            key="follow_ups_due",
            label="Follow-Ups Due",
            value=follow_ups_due,
            href="/follow-ups",
        ),
        MetricCard(
            key="final_rounds",
            label="Final Rounds",
            value=finals,
            href="/applications?status=final_round",
        ),
        MetricCard(
            key="offers",
            label="Offers",
            value=offers,
            href="/applications?column=offer",
        ),
    ]


def _awaiting_outcome(
    db: Session, workspace: Workspace, person_ids: list[str], registry
) -> list[UpcomingInterview]:
    """Interviews that have happened but have no result yet (spec §49)."""
    from app.domains.interviews.service import stages_awaiting_outcome

    rows = stages_awaiting_outcome(db, workspace, person_ids)
    out: list[UpcomingInterview] = []
    for stage, application, person in rows[:8]:
        info = registry.get(stage.type_key)
        out.append(
            UpcomingInterview(
                stage_id=stage.id,
                event_id=None,
                application_id=application.id,
                person_id=person.id,
                person_name=person.display_name,
                person_color=person.color,
                person_initials=person.initials,
                company_name=application.company_name,
                job_title=application.job_title,
                stage_name=stage.name,
                type_key=info.key,
                type_label=info.label,
                type_short_label=info.short_label,
                round_number=stage.round_number,
                stage_badge=stage_badge(stage.round_number, info.short_label),
                status=stage.status,
                outcome=stage.outcome,
                starts_at=stage.scheduled_start or stage.scheduled_end,  # type: ignore[arg-type]
                ends_at=stage.scheduled_end or stage.scheduled_start,  # type: ignore[arg-type]
                timezone=person.timezone,
                meeting_url=None,
                location=None,
            )
        )
    return out


# --------------------------------------------------------------------------
# Needs Attention
# --------------------------------------------------------------------------


def build_needs_attention(
    db: Session,
    workspace: Workspace,
    people: list[Person],
    *,
    today: date | None = None,
    limit: int = ATTENTION_LIMIT,
) -> list[AttentionItem]:
    """The panel that answers "what needs my attention?" (spec §22)."""
    person_ids = [p.id for p in people]
    if not person_ids:
        return []

    registry = load_registry(db, workspace.id)
    now = utcnow()
    tz = workspace.default_timezone
    today = today or local_date(now, tz)
    by_person = {p.id: p for p in people}
    items: list[AttentionItem] = []

    applications = {
        a.id: a
        for a in db.scalars(
            select(Application).where(
                Application.person_id.in_(person_ids),
                Application.archived_at.is_(None),
            )
        )
    }

    # 1. Overdue follow-ups -------------------------------------------------
    for follow_up in db.scalars(
        select(FollowUp)
        .where(
            FollowUp.person_id.in_(person_ids),
            FollowUp.status.in_([FollowUpStatus.OPEN.value, FollowUpStatus.SNOOZED.value]),
        )
        .order_by(FollowUp.due_date)
    ):
        person = by_person.get(follow_up.person_id)
        application = applications.get(follow_up.application_id)
        if person is None or application is None:
            continue
        person_today = local_date(now, person.timezone)
        state = compute_state(
            stored_status=follow_up.status,
            due_date=follow_up.due_date,
            today=person_today,
            snoozed_until=follow_up.snoozed_until,
        )
        if state.status not in (
            FollowUpComputedStatus.OVERDUE,
            FollowUpComputedStatus.DUE_TODAY,
        ):
            continue
        items.append(
            AttentionItem(
                id=f"followup:{follow_up.id}",
                kind="overdue_follow_up",
                severity="high"
                if state.status is FollowUpComputedStatus.OVERDUE
                else "medium",
                person_id=person.id,
                person_name=person.display_name,
                person_color=person.color,
                person_initials=person.initials,
                company_name=application.company_name,
                job_title=application.job_title,
                headline=follow_up.title,
                detail=describe(state),
                application_id=application.id,
                interview_stage_id=follow_up.interview_stage_id,
                follow_up_id=follow_up.id,
                due_date=follow_up.due_date,
                actions=["complete", "snooze", "change_date", "open_application"],
            )
        )

    # 2. Interviews that happened but have no result ------------------------
    stage_rows = db.execute(
        select(InterviewStage, Application)
        .join(Application, Application.id == InterviewStage.application_id)
        .where(
            Application.person_id.in_(person_ids),
            Application.archived_at.is_(None),
            InterviewStage.status == InterviewStatus.COMPLETED.value,
            InterviewStage.outcome.in_(
                [InterviewOutcome.WAITING.value, InterviewOutcome.PENDING.value]
            ),
            InterviewStage.scheduled_end.is_not(None),
        )
        .order_by(InterviewStage.scheduled_end.desc())
    )
    for stage, application in stage_rows:
        person = by_person.get(application.person_id)
        if person is None or stage.scheduled_end is None:
            continue
        days = (today - local_date(stage.scheduled_end, person.timezone)).days
        if days < workspace.followup_after_interview_business_days:
            continue
        badge = stage_badge(stage.round_number, registry.short_label(stage.type_key))
        items.append(
            AttentionItem(
                id=f"stage:{stage.id}",
                kind="awaiting_result",
                severity="high" if days >= 7 else "medium",
                person_id=person.id,
                person_name=person.display_name,
                person_color=person.color,
                person_initials=person.initials,
                company_name=application.company_name,
                job_title=application.job_title,
                headline=f"{stage.name} — still no result",
                detail=f"Completed {days} day{'s' if days != 1 else ''} ago",
                application_id=application.id,
                interview_stage_id=stage.id,
                stage_badge=badge,
                happens_at=stage.scheduled_end,
                actions=["set_outcome", "create_follow_up", "open_application"],
            )
        )

    # 3. Interviews happening today or tomorrow -----------------------------
    _, soon_end = day_bounds(today, tz)
    _, tomorrow_end = day_bounds(today + timedelta(days=1), tz)
    for row in upcoming_interviews(
        db, workspace, person_ids, start=now, end=tomorrow_end, limit=8, registry=registry
    ):
        is_today = row.starts_at < soon_end
        items.append(
            AttentionItem(
                id=f"upcoming:{row.event_id or row.stage_id}",
                kind="upcoming_interview",
                severity="medium" if is_today else "low",
                person_id=row.person_id,
                person_name=row.person_name,
                person_color=row.person_color,
                person_initials=row.person_initials,
                company_name=row.company_name,
                job_title=row.job_title,
                headline=f"{row.stage_name}",
                detail="Interview today" if is_today else "Interview tomorrow",
                application_id=row.application_id,
                interview_stage_id=row.stage_id,
                stage_badge=row.stage_badge,
                happens_at=row.starts_at,
                actions=["open_application", "reschedule"],
            )
        )

    # 4. Waiting for feedback beyond the threshold --------------------------
    threshold = workspace.waiting_for_feedback_threshold_days
    for application in applications.values():
        if application.status != ApplicationStatus.WAITING_FOR_FEEDBACK.value:
            continue
        person = by_person.get(application.person_id)
        if person is None:
            continue
        days = (now - application.last_activity_at).days
        if days < threshold:
            continue
        items.append(
            AttentionItem(
                id=f"waiting:{application.id}",
                kind="waiting_too_long",
                severity="medium",
                person_id=person.id,
                person_name=person.display_name,
                person_color=person.color,
                person_initials=person.initials,
                company_name=application.company_name,
                job_title=application.job_title,
                headline="Waiting for feedback",
                detail=f"No response for {days} days",
                application_id=application.id,
                actions=["create_follow_up", "open_application", "mark_ghosted"],
            )
        )

    # 5. No activity at all -> suggest marking as ghosted --------------------
    ghost_threshold = workspace.no_activity_ghosted_threshold_days
    for application in applications.values():
        status = ApplicationStatus(application.status)
        if status in {
            ApplicationStatus.GHOSTED,
            ApplicationStatus.REJECTED,
            ApplicationStatus.ACCEPTED,
            ApplicationStatus.WITHDRAWN,
            ApplicationStatus.SAVED,
        } or status in OFFER_STATUSES:
            continue
        person = by_person.get(application.person_id)
        if person is None:
            continue
        days = (now - application.last_activity_at).days
        if days < ghost_threshold:
            continue
        items.append(
            AttentionItem(
                id=f"stale:{application.id}",
                kind="no_activity",
                severity="low",
                person_id=person.id,
                person_name=person.display_name,
                person_color=person.color,
                person_initials=person.initials,
                company_name=application.company_name,
                job_title=application.job_title,
                headline="No activity",
                detail=f"Nothing has happened for {days} days",
                application_id=application.id,
                actions=["mark_ghosted", "create_follow_up", "open_application"],
            )
        )

    # 6. Same-person scheduling conflicts -----------------------------------
    from app.domains.calendar.conflicts import find_conflicts

    conflict_window_end = now + timedelta(days=14)
    for index, conflict in enumerate(
        find_conflicts(db, workspace, people, start=now, end=conflict_window_end)
    ):
        items.append(
            AttentionItem(
                id=f"conflict:{index}",
                kind="scheduling_conflict",
                severity="high",
                person_id=conflict.person_id,
                person_name=conflict.person_name,
                person_color=conflict.person_color,
                person_initials="",
                company_name=conflict.first_title,
                headline="Scheduling conflict",
                detail=(
                    f"{conflict.first_title} overlaps {conflict.second_title} "
                    f"by {conflict.overlap_minutes} minutes"
                ),
                actions=["open_calendar"],
            )
        )

    severity_order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda i: (severity_order.get(i.severity, 3), i.due_date or today))
    return items[:limit]
