"""Application CRUD, filtering, pipeline and detail assembly (spec §11-§13, §17)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.timeutils import local_date, utcnow
from app.domains.activity import service as activity_service
from app.domains.followups.status import compute_state
from app.domains.interviews.serialize import stage_to_out
from app.domains.interviews.types import TypeRegistry, load_registry, stage_badge
from app.enums import (
    COLUMN_DEFAULT_STATUS,
    STATUS_TO_COLUMN,
    ActivityType,
    ApplicationStatus,
    FollowUpComputedStatus,
    FollowUpStatus,
    InterviewOutcome,
    InterviewStatus,
    PipelineColumn,
)
from app.models import (
    Application,
    ApplicationNote,
    FollowUp,
    InterviewStage,
    Person,
    Workspace,
)
from app.schemas.application import (
    ApplicationCreate,
    ApplicationDetail,
    ApplicationNoteOut,
    ApplicationOut,
    ApplicationSheet,
    ApplicationUpdate,
    NextInterviewSummary,
    PipelineCard,
    PipelineColumnOut,
    PipelineOut,
    SheetDay,
    SheetRow,
    SheetTab,
)
from app.schemas.person import PersonOut

PIPELINE_COLUMN_LABELS: dict[PipelineColumn, str] = {
    PipelineColumn.APPLIED: "Applied",
    PipelineColumn.SCREENING: "Screening",
    PipelineColumn.INTERVIEWING: "Interviewing",
    PipelineColumn.FINAL: "Final",
    PipelineColumn.OFFER: "Offer",
    PipelineColumn.CLOSED: "Closed",
}


@dataclass
class ApplicationFilters:
    """Every filter from spec §32."""

    person_ids: list[str] | None = None
    statuses: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    type_keys: list[str] = field(default_factory=list)
    outcomes: list[str] = field(default_factory=list)
    work_modes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    company: str | None = None
    search: str | None = None
    applied_from: date | None = None
    applied_to: date | None = None
    has_upcoming_interview: bool | None = None
    has_overdue_follow_up: bool | None = None
    include_archived: bool = False
    sort: str = "last_activity"


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------


def get_application(db: Session, workspace: Workspace, application_id: str) -> Application:
    application = db.get(Application, application_id)
    if application is None or application.workspace_id != workspace.id:
        raise NotFoundError(
            "That application could not be found.", code="application_not_found"
        )
    return application


def touch(application: Application) -> None:
    """Mark activity on an application (drives the "days since activity" badge)."""
    application.last_activity_at = utcnow()


# --------------------------------------------------------------------------
# Query building
# --------------------------------------------------------------------------


def _apply_filters(stmt: Select, filters: ApplicationFilters, now: datetime) -> Select:
    if filters.person_ids is not None:
        stmt = stmt.where(Application.person_id.in_(filters.person_ids))
    if not filters.include_archived:
        stmt = stmt.where(Application.archived_at.is_(None))

    statuses = set(filters.statuses)
    if filters.columns:
        # A column filter expands into the set of statuses that map to it.
        for status, column in STATUS_TO_COLUMN.items():
            if column.value in filters.columns:
                statuses.add(status.value)
    if statuses:
        stmt = stmt.where(Application.status.in_(sorted(statuses)))

    if filters.work_modes:
        stmt = stmt.where(Application.work_mode.in_(filters.work_modes))
    if filters.sources:
        stmt = stmt.where(Application.source.in_(filters.sources))
    if filters.company:
        stmt = stmt.where(Application.company_name.ilike(f"%{filters.company}%"))
    if filters.applied_from:
        stmt = stmt.where(Application.applied_date >= filters.applied_from)
    if filters.applied_to:
        stmt = stmt.where(Application.applied_date <= filters.applied_to)

    if filters.search:
        # Global search across company, title, notes and person name (spec §32).
        term = f"%{filters.search.strip()}%"
        stmt = stmt.join(Person, Person.id == Application.person_id).where(
            or_(
                Application.company_name.ilike(term),
                Application.job_title.ilike(term),
                Application.notes.ilike(term),
                Application.location.ilike(term),
                Person.name.ilike(term),
                Person.display_name.ilike(term),
            )
        )

    if filters.type_keys or filters.outcomes:
        stage_stmt = select(InterviewStage.application_id)
        if filters.type_keys:
            stage_stmt = stage_stmt.where(InterviewStage.type_key.in_(filters.type_keys))
        if filters.outcomes:
            stage_stmt = stage_stmt.where(InterviewStage.outcome.in_(filters.outcomes))
        stmt = stmt.where(Application.id.in_(stage_stmt))

    if filters.has_upcoming_interview is not None:
        upcoming = select(InterviewStage.application_id).where(
            InterviewStage.status == InterviewStatus.SCHEDULED.value,
            InterviewStage.scheduled_start >= now,
        )
        stmt = stmt.where(
            Application.id.in_(upcoming)
            if filters.has_upcoming_interview
            else ~Application.id.in_(upcoming)
        )

    if filters.has_overdue_follow_up is not None:
        # `due_date < today` is evaluated in SQL against the workspace's notion
        # of today; per-person timezone nuance is applied when decorating.
        overdue = select(FollowUp.application_id).where(
            FollowUp.status == FollowUpStatus.OPEN.value,
            FollowUp.due_date < now.date(),
        )
        stmt = stmt.where(
            Application.id.in_(overdue)
            if filters.has_overdue_follow_up
            else ~Application.id.in_(overdue)
        )

    return stmt


_SORTS = {
    "last_activity": Application.last_activity_at.desc(),
    "applied_date": Application.applied_date.desc(),
    "company": Application.company_name.asc(),
    "created": Application.created_at.desc(),
}


def list_applications(
    db: Session,
    workspace: Workspace,
    filters: ApplicationFilters,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Application], int]:
    now = utcnow()
    base = select(Application).where(Application.workspace_id == workspace.id)
    base = _apply_filters(base, filters, now)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = db.scalar(count_stmt) or 0

    order = _SORTS.get(filters.sort, _SORTS["last_activity"])
    stmt = (
        base.options(selectinload(Application.person))
        .order_by(order)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).unique()), total


# --------------------------------------------------------------------------
# Derived-field decoration
# --------------------------------------------------------------------------


@dataclass
class _Derived:
    next_interview: dict[str, NextInterviewSummary]
    current_badge: dict[str, str]
    stage_counts: dict[str, int]
    open_follow_ups: dict[str, int]
    overdue_follow_ups: set[str]


def _collect_derived(
    db: Session, application_ids: list[str], registry: TypeRegistry, people: dict[str, Person]
) -> _Derived:
    """One grouped query per derived field, never one per row (spec §56)."""
    next_interview: dict[str, NextInterviewSummary] = {}
    current_badge: dict[str, str] = {}
    stage_counts: dict[str, int] = {}
    open_follow_ups: dict[str, int] = {}
    overdue: set[str] = set()

    if not application_ids:
        return _Derived({}, {}, {}, {}, set())

    now = utcnow()

    for app_id, count in db.execute(
        select(InterviewStage.application_id, func.count(InterviewStage.id))
        .where(InterviewStage.application_id.in_(application_ids))
        .group_by(InterviewStage.application_id)
    ):
        stage_counts[app_id] = int(count or 0)

    # Next scheduled interview per application.
    upcoming_stages = db.scalars(
        select(InterviewStage)
        .where(
            InterviewStage.application_id.in_(application_ids),
            InterviewStage.status == InterviewStatus.SCHEDULED.value,
            InterviewStage.scheduled_start.is_not(None),
            InterviewStage.scheduled_start >= now,
        )
        .order_by(InterviewStage.scheduled_start.asc())
    )
    for stage in upcoming_stages:
        if stage.application_id in next_interview:
            continue  # already have the earliest one
        info = registry.get(stage.type_key)
        badge = stage_badge(stage.round_number, info.short_label)
        next_interview[stage.application_id] = NextInterviewSummary(
            stage_id=stage.id,
            stage_name=stage.name,
            stage_badge=badge,
            type_key=stage.type_key,
            type_short_label=info.short_label,
            round_number=stage.round_number,
            starts_at=stage.scheduled_start,  # type: ignore[arg-type]
            status=stage.status,
        )
        current_badge[stage.application_id] = badge

    # For applications with nothing upcoming, the "current" step is the most
    # advanced stage on record.
    remaining = [a for a in application_ids if a not in current_badge]
    if remaining:
        recent_stages = db.scalars(
            select(InterviewStage)
            .where(InterviewStage.application_id.in_(remaining))
            .order_by(
                InterviewStage.application_id,
                InterviewStage.sequence.desc(),
                InterviewStage.created_at.desc(),
            )
        )
        for stage in recent_stages:
            if stage.application_id in current_badge:
                continue
            info = registry.get(stage.type_key)
            current_badge[stage.application_id] = stage_badge(
                stage.round_number, info.short_label
            )

    # Follow-up counts. Overdue is decided per person timezone, so the rows are
    # fetched and evaluated in Python rather than compared to a single "today".
    follow_ups = db.scalars(
        select(FollowUp).where(
            FollowUp.application_id.in_(application_ids),
            FollowUp.status.in_([FollowUpStatus.OPEN.value, FollowUpStatus.SNOOZED.value]),
        )
    )
    for follow_up in follow_ups:
        open_follow_ups[follow_up.application_id] = (
            open_follow_ups.get(follow_up.application_id, 0) + 1
        )
        person = people.get(follow_up.person_id)
        today = local_date(now, person.timezone if person else None)
        state = compute_state(
            stored_status=follow_up.status,
            due_date=follow_up.due_date,
            today=today,
            snoozed_until=follow_up.snoozed_until,
        )
        if state.status is FollowUpComputedStatus.OVERDUE:
            overdue.add(follow_up.application_id)

    return _Derived(next_interview, current_badge, stage_counts, open_follow_ups, overdue)


def _days_since(value: datetime, now: datetime) -> int:
    return max(0, (now - value).days)


def decorate_applications(
    db: Session,
    workspace: Workspace,
    applications: list[Application],
    *,
    registry: TypeRegistry | None = None,
) -> list[ApplicationOut]:
    registry = registry or load_registry(db, workspace.id)
    now = utcnow()
    ids = [a.id for a in applications]

    person_ids = {a.person_id for a in applications}
    people = {
        p.id: p
        for p in db.scalars(select(Person).where(Person.id.in_(person_ids)))
    }
    derived = _collect_derived(db, ids, registry, people)

    results: list[ApplicationOut] = []
    for application in applications:
        out = ApplicationOut.model_validate(application)
        person = people.get(application.person_id)
        out.person = PersonOut.model_validate(person) if person else None
        out.pipeline_column = STATUS_TO_COLUMN[
            ApplicationStatus(application.status)
        ].value
        out.days_since_activity = _days_since(application.last_activity_at, now)
        out.stage_count = derived.stage_counts.get(application.id, 0)
        out.next_interview = derived.next_interview.get(application.id)
        out.current_stage_badge = derived.current_badge.get(application.id)
        out.open_follow_up_count = derived.open_follow_ups.get(application.id, 0)
        out.has_overdue_follow_up = application.id in derived.overdue_follow_ups
        results.append(out)
    return results


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------


def build_pipeline(
    db: Session, workspace: Workspace, filters: ApplicationFilters
) -> PipelineOut:
    """Kanban board. Pulls every matching application — a personal job search
    does not reach a size where this needs paging, and the board is meaningless
    partially filled."""
    now = utcnow()
    stmt = select(Application).where(Application.workspace_id == workspace.id)
    stmt = _apply_filters(stmt, filters, now).order_by(
        Application.last_activity_at.desc()
    )
    applications = list(db.scalars(stmt).unique())
    decorated = decorate_applications(db, workspace, applications)

    buckets: dict[str, list[PipelineCard]] = {c.value: [] for c in PipelineColumn}
    for out in decorated:
        person = out.person
        buckets[out.pipeline_column].append(
            PipelineCard(
                id=out.id,
                person_id=out.person_id,
                person_name=person.display_name if person else "Unknown",
                person_color=person.color if person else "#64748b",
                person_initials=person.initials if person else "?",
                company_name=out.company_name,
                job_title=out.job_title,
                status=out.status,
                priority=out.priority,
                current_stage_badge=out.current_stage_badge,
                next_interview=out.next_interview,
                days_since_activity=out.days_since_activity,
                open_follow_up_count=out.open_follow_up_count,
                has_overdue_follow_up=out.has_overdue_follow_up,
            )
        )

    columns = [
        PipelineColumnOut(
            key=column.value,
            label=PIPELINE_COLUMN_LABELS[column],
            count=len(buckets[column.value]),
            cards=buckets[column.value],
        )
        for column in PipelineColumn
    ]
    return PipelineOut(columns=columns, total=len(decorated))


# --------------------------------------------------------------------------
# Sheet view
# --------------------------------------------------------------------------


def _day_label(day: date | None) -> str:
    """`Tue 19 Aug 2026`, or a name for the undated bucket.

    Built by hand rather than with `%-d`, which is a glibc extension and raises
    on Windows — where this app is also run.
    """
    if day is None:
        return "No date recorded"
    return f"{day.strftime('%a')} {day.day} {day.strftime('%b')} {day.year}"


def build_sheet(
    db: Session,
    workspace: Workspace,
    *,
    people: list[Person],
    person_id: str | None,
    editable_person_ids: set[str] | None,
    search: str | None = None,
    include_archived: bool = False,
) -> ApplicationSheet:
    """One person's applications as a spreadsheet, grouped by the day applied.

    Grouping happens here rather than in the browser because `applied_date` is
    already anchored to the person's own timezone (see `create_application`).
    Regrouping client-side would re-date every row into whatever zone the
    viewer's laptop happens to be in.

    Every row for the person is returned. A job search does not reach a size
    where a spreadsheet needs paging, and a partially filled one would make the
    per-day counts wrong — which is the whole point of the view.
    """
    def can_edit(pid: str) -> bool:
        return editable_person_ids is None or pid in editable_person_ids

    # Totals per tab ignore the search, so the tab bar does not reshuffle while
    # the user is typing.
    totals = dict(
        db.execute(
            select(Application.person_id, func.count(Application.id))
            .where(
                Application.workspace_id == workspace.id,
                Application.person_id.in_([p.id for p in people] or [""]),
                *(() if include_archived else (Application.archived_at.is_(None),)),
            )
            .group_by(Application.person_id)
        ).all()
    )

    tabs = [
        SheetTab(
            person_id=person.id,
            name=person.display_name,
            initials=person.initials,
            color=person.color,
            total=totals.get(person.id, 0),
            can_edit=can_edit(person.id),
        )
        for person in people
    ]

    # Default to the first tab, and ignore an id that is not on the bar.
    known = {person.id for person in people}
    active = person_id if person_id in known else (people[0].id if people else None)
    if active is None:
        return ApplicationSheet(
            tabs=[], person_id=None, can_edit=False, days=[], matched=0, total=0
        )

    filters = ApplicationFilters(
        person_ids=[active],
        search=search or None,
        include_archived=include_archived,
        sort="applied_date",
    )
    stmt = _apply_filters(
        select(Application).where(Application.workspace_id == workspace.id),
        filters,
        utcnow(),
    )
    # Oldest first, like a spreadsheet you append to: the newest row ends up at
    # the bottom, next to the blank row you type into, instead of jumping to the
    # top and away from the cursor. `created_at` breaks ties within a day so the
    # order is insertion order and does not reshuffle when a row is edited.
    rows = list(
        db.scalars(
            stmt.order_by(
                Application.applied_date.asc(),
                Application.created_at.asc(),
            )
        ).unique()
    )

    grouped: dict[date | None, list[SheetRow]] = {}
    for application in rows:
        grouped.setdefault(application.applied_date, []).append(
            SheetRow(
                id=application.id,
                person_id=application.person_id,
                applied_date=application.applied_date,
                company_name=application.company_name,
                job_title=application.job_title,
                job_url=application.job_url,
                status=application.status,
                is_archived=application.archived_at is not None,
            )
        )

    # Oldest day at the top, newest at the bottom. Undated rows — saved but not
    # yet applied — go above the dated run rather than below it, so the bottom
    # of the sheet stays "now": the newest day, then the blank add row.
    ordered = sorted(
        grouped.items(),
        key=lambda kv: (kv[0] is not None, kv[0] or date.min),
    )
    days = [
        SheetDay(date=day, label=_day_label(day), count=len(items), rows=items)
        for day, items in ordered
    ]

    dated = [day for day in days if day.date is not None]
    busiest = max(dated, key=lambda d: (d.count, d.date), default=None)

    return ApplicationSheet(
        tabs=tabs,
        person_id=active,
        can_edit=can_edit(active),
        days=days,
        matched=len(rows),
        total=totals.get(active, 0),
        busiest_day=busiest.date if busiest else None,
        busiest_day_count=busiest.count if busiest else 0,
    )


# --------------------------------------------------------------------------
# Mutations
# --------------------------------------------------------------------------


def create_application(
    db: Session, workspace: Workspace, payload: ApplicationCreate
) -> Application:
    person = db.get(Person, payload.person_id)
    if person is None or person.workspace_id != workspace.id:
        raise ValidationError(
            "Choose a person for this application.", code="person_not_found"
        )

    now = utcnow()
    applied = payload.applied_date
    if applied is None and payload.status != ApplicationStatus.SAVED:
        # Quick Add default (spec §50): today, in the person's own timezone.
        applied = local_date(now, person.timezone)

    application = Application(
        workspace_id=workspace.id,
        person_id=person.id,
        company_name=payload.company_name.strip(),
        job_title=payload.job_title.strip(),
        job_url=payload.job_url,
        location=payload.location,
        work_mode=payload.work_mode.value,
        employment_type=payload.employment_type.value,
        salary_min=payload.salary_min,
        salary_max=payload.salary_max,
        salary_currency=payload.salary_currency,
        hourly_rate=payload.hourly_rate,
        source=payload.source,
        applied_date=applied,
        status=payload.status.value,
        priority=payload.priority.value,
        notes=payload.notes,
        resume_version_id=payload.resume_version_id,
        last_activity_at=now,
    )
    db.add(application)
    db.flush()

    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.APPLICATION_CREATED,
        message=(
            f"{person.display_name} added {application.company_name} — "
            f"{application.job_title}"
        ),
        person_id=person.id,
        application_id=application.id,
        meta={"company": application.company_name, "status": application.status},
    )
    db.commit()
    return application


def update_application(
    db: Session, workspace: Workspace, application_id: str, payload: ApplicationUpdate
) -> Application:
    application = get_application(db, workspace, application_id)
    data = payload.model_dump(exclude_unset=True)
    previous_status = application.status

    if data.get("person_id"):
        person = db.get(Person, data["person_id"])
        if person is None or person.workspace_id != workspace.id:
            raise ValidationError("Unknown person.", code="person_not_found")
        application.person_id = person.id

    simple_fields = (
        "company_name",
        "job_title",
        "job_url",
        "location",
        "salary_min",
        "salary_max",
        "salary_currency",
        "hourly_rate",
        "source",
        "applied_date",
        "notes",
        "resume_version_id",
    )
    for key in simple_fields:
        if key in data:
            setattr(application, key, data[key])

    for key in ("work_mode", "employment_type", "priority"):
        if key in data and data[key] is not None:
            value = data[key]
            setattr(application, key, value.value if hasattr(value, "value") else value)

    if "status" in data and data["status"] is not None:
        new_status = data["status"]
        application.status = (
            new_status.value if hasattr(new_status, "value") else new_status
        )

    touch(application)

    if application.status != previous_status:
        _log_status_change(db, workspace, application, previous_status)
        from app.domains.followups import rules as followup_rules

        followup_rules.on_application_status_changed(
            db, workspace, application, previous_status
        )
    else:
        activity_service.log(
            db,
            workspace_id=workspace.id,
            activity_type=ActivityType.APPLICATION_UPDATED,
            message=f"{application.company_name} application was updated",
            person_id=application.person_id,
            application_id=application.id,
        )

    db.commit()
    return application


def _log_status_change(
    db: Session, workspace: Workspace, application: Application, previous_status: str
) -> None:
    person = db.get(Person, application.person_id)
    name = person.display_name if person else "Someone"
    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.APPLICATION_STATUS_CHANGED,
        message=(
            f"{name}'s {application.company_name} application moved from "
            f"{_humanise(previous_status)} to {_humanise(application.status)}"
        ),
        person_id=application.person_id,
        application_id=application.id,
        meta={"from": previous_status, "to": application.status},
    )


def _humanise(value: str) -> str:
    return value.replace("_", " ").title()


def change_status(
    db: Session,
    workspace: Workspace,
    application_id: str,
    *,
    status: ApplicationStatus | None = None,
    column: PipelineColumn | None = None,
) -> Application:
    """Set status directly, or infer it from the pipeline column a card was
    dropped into (spec §13)."""
    application = get_application(db, workspace, application_id)
    previous = application.status

    if status is None and column is not None:
        current_column = STATUS_TO_COLUMN[ApplicationStatus(previous)]
        if current_column is column:
            return application  # dropped back where it started
        status = COLUMN_DEFAULT_STATUS[column]

    if status is None:  # pragma: no cover - schema guarantees one is present
        raise ValidationError("No status supplied.", code="missing_status")

    if status.value == previous:
        return application

    application.status = status.value
    if status is ApplicationStatus.ARCHIVED:
        application.archived_at = utcnow()
    touch(application)

    _log_status_change(db, workspace, application, previous)
    from app.domains.followups import rules as followup_rules

    followup_rules.on_application_status_changed(db, workspace, application, previous)
    db.commit()
    return application


def archive_application(
    db: Session, workspace: Workspace, application_id: str
) -> Application:
    application = get_application(db, workspace, application_id)
    if application.archived_at is None:
        application.archived_at = utcnow()
        activity_service.log(
            db,
            workspace_id=workspace.id,
            activity_type=ActivityType.APPLICATION_ARCHIVED,
            message=f"{application.company_name} application was archived",
            person_id=application.person_id,
            application_id=application.id,
        )
        db.commit()
    return application


def restore_application(
    db: Session, workspace: Workspace, application_id: str
) -> Application:
    application = get_application(db, workspace, application_id)
    if application.archived_at is not None:
        application.archived_at = None
        if application.status == ApplicationStatus.ARCHIVED.value:
            application.status = ApplicationStatus.APPLIED.value
        touch(application)
        activity_service.log(
            db,
            workspace_id=workspace.id,
            activity_type=ActivityType.APPLICATION_RESTORED,
            message=f"{application.company_name} application was restored",
            person_id=application.person_id,
            application_id=application.id,
        )
        db.commit()
    return application


def delete_application(db: Session, workspace: Workspace, application_id: str) -> None:
    """Hard delete. Only allowed while nothing of substance hangs off it —
    otherwise archiving is the right move (spec §36)."""
    application = get_application(db, workspace, application_id)
    stage_count = (
        db.scalar(
            select(func.count(InterviewStage.id)).where(
                InterviewStage.application_id == application.id
            )
        )
        or 0
    )
    if stage_count:
        raise ConflictError(
            (
                f"This application has {stage_count} interview"
                f"{'s' if stage_count != 1 else ''} recorded. Archive it instead "
                "so the history is kept."
            ),
            code="application_has_history",
            details={"stage_count": stage_count},
        )
    db.delete(application)
    db.commit()


# --------------------------------------------------------------------------
# Detail page
# --------------------------------------------------------------------------


def build_detail(
    db: Session, workspace: Workspace, application_id: str
) -> ApplicationDetail:
    application = get_application(db, workspace, application_id)
    registry = load_registry(db, workspace.id)

    stages = list(
        db.scalars(
            select(InterviewStage)
            .where(InterviewStage.application_id == application.id)
            .options(selectinload(InterviewStage.events))
            .order_by(InterviewStage.sequence, InterviewStage.created_at)
        )
    )
    notes = list(
        db.scalars(
            select(ApplicationNote)
            .where(ApplicationNote.application_id == application.id)
            .order_by(ApplicationNote.created_at.desc())
        )
    )

    base = decorate_applications(db, workspace, [application], registry=registry)[0]
    detail = ApplicationDetail(**base.model_dump())
    detail.stages = [stage_to_out(s, registry) for s in stages]
    detail.notes_log = [ApplicationNoteOut.model_validate(n) for n in notes]
    return detail


def add_note(
    db: Session, workspace: Workspace, application_id: str, body: str
) -> ApplicationNote:
    application = get_application(db, workspace, application_id)
    note = ApplicationNote(application_id=application.id, body=body.strip())
    db.add(note)
    touch(application)
    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.NOTE_ADDED,
        message=f"Note added to {application.company_name}",
        person_id=application.person_id,
        application_id=application.id,
    )
    db.commit()
    return note


def delete_note(db: Session, workspace: Workspace, application_id: str, note_id: str) -> None:
    application = get_application(db, workspace, application_id)
    note = db.get(ApplicationNote, note_id)
    if note is None or note.application_id != application.id:
        raise NotFoundError("That note could not be found.", code="note_not_found")
    db.delete(note)
    db.commit()


def distinct_sources(db: Session, workspace: Workspace) -> list[str]:
    """Populates the source filter dropdown."""
    return [
        s
        for s in db.scalars(
            select(Application.source)
            .where(
                Application.workspace_id == workspace.id, Application.source.is_not(None)
            )
            .distinct()
            .order_by(Application.source)
        )
        if s
    ]


def distinct_companies(db: Session, workspace: Workspace) -> list[str]:
    return list(
        db.scalars(
            select(Application.company_name)
            .where(Application.workspace_id == workspace.id)
            .distinct()
            .order_by(Application.company_name)
        )
    )


def stage_outcome_values() -> list[str]:
    return [o.value for o in InterviewOutcome]
