"""Interview stage and event management (spec §14-§17, §47, §49)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import NotFoundError, ValidationError
from app.core.timeutils import local_date, utcnow
from app.domains.activity import service as activity_service
from app.domains.applications.service import get_application, touch
from app.domains.interviews.types import (
    TypeRegistry,
    default_stage_name,
    load_registry,
    stage_badge,
)
from app.enums import (
    DECIDED_OUTCOMES,
    ActivityType,
    ApplicationStatus,
    InterviewOutcome,
    InterviewStatus,
)
from app.models import (
    Application,
    InterviewEvent,
    InterviewStage,
    InterviewType,
    Person,
    Workspace,
)
from app.schemas.interview import (
    InterviewEventCreate,
    InterviewEventUpdate,
    InterviewOutcomeUpdate,
    InterviewSearchResult,
    InterviewStageCreate,
    InterviewStageUpdate,
    UpcomingInterview,
)

DEFAULT_EVENT_MINUTES = 60


# --------------------------------------------------------------------------
# Status / outcome coupling (spec §15)
# --------------------------------------------------------------------------


def normalise_status_outcome(
    status: InterviewStatus, outcome: InterviewOutcome
) -> tuple[InterviewStatus, InterviewOutcome]:
    """Keep the two fields consistent without collapsing them into one.

    Status answers "has it happened?", outcome answers "what was the result?".
    They stay independent — the spec's own example is status=Completed with
    outcome=Waiting — but some combinations are simply contradictory, and those
    are corrected here.
    """
    # A verdict implies the interview happened.
    if outcome in DECIDED_OUTCOMES and status in (
        InterviewStatus.PLANNED,
        InterviewStatus.SCHEDULED,
    ):
        status = InterviewStatus.COMPLETED

    if outcome is InterviewOutcome.WAITING and status in (
        InterviewStatus.PLANNED,
        InterviewStatus.SCHEDULED,
    ):
        status = InterviewStatus.COMPLETED

    if outcome in (InterviewOutcome.CANCELLED, InterviewOutcome.WITHDRAWN):
        status = InterviewStatus.CANCELLED

    # ... and the reverse: a lifecycle state implies a default verdict.
    if status is InterviewStatus.COMPLETED and outcome is InterviewOutcome.PENDING:
        outcome = InterviewOutcome.WAITING
    if status is InterviewStatus.CANCELLED and outcome is InterviewOutcome.PENDING:
        outcome = InterviewOutcome.CANCELLED
    if status is InterviewStatus.NO_SHOW and outcome is InterviewOutcome.PENDING:
        outcome = InterviewOutcome.UNKNOWN

    return status, outcome


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------


def get_stage(db: Session, workspace: Workspace, stage_id: str) -> InterviewStage:
    stage = db.get(InterviewStage, stage_id)
    if stage is None:
        raise NotFoundError("That interview could not be found.", code="stage_not_found")
    application = db.get(Application, stage.application_id)
    if application is None or application.workspace_id != workspace.id:
        raise NotFoundError("That interview could not be found.", code="stage_not_found")
    return stage


def _validate_type_key(db: Session, workspace: Workspace, key: str) -> str:
    exists = db.scalar(
        select(func.count(InterviewType.id)).where(
            InterviewType.workspace_id == workspace.id, InterviewType.key == key
        )
    )
    if not exists:
        raise ValidationError(
            f"Unknown interview type: {key}", code="unknown_interview_type"
        )
    return key


def recompute_stage_window(stage: InterviewStage) -> None:
    """Mirror the stage's schedule from its events.

    A stage spans all of its events, so a four-slot final loop reads as one
    block from 9:00 to 15:00 (spec §16). With no events, any manually set
    window is left alone.
    """
    if not stage.events:
        return
    stage.scheduled_start = min(e.starts_at for e in stage.events)
    stage.scheduled_end = max(e.ends_at for e in stage.events)
    if stage.status is InterviewStatus.PLANNED.value:
        stage.status = InterviewStatus.SCHEDULED.value


def _next_sequence(db: Session, application_id: str) -> int:
    current = db.scalar(
        select(func.max(InterviewStage.sequence)).where(
            InterviewStage.application_id == application_id
        )
    )
    return (current or 0) + 1


def _next_round_number(db: Session, application_id: str) -> int:
    current = db.scalar(
        select(func.max(InterviewStage.round_number)).where(
            InterviewStage.application_id == application_id
        )
    )
    return (current or 0) + 1


def search_stages(
    db: Session,
    workspace: Workspace,
    *,
    person_ids: list[str] | None = None,
    search: str | None = None,
    limit: int = 25,
) -> list[InterviewSearchResult]:
    """Find past interviews by what the user remembers about them.

    Matches the stage name, the company and the job title, because "the
    Anthropic recruiter screen" is how people refer to a round — not by the
    application row it belongs to. Used when attaching a later-round calendar
    event to a journey that is already under way.
    """
    from sqlalchemy import or_

    stmt = (
        select(InterviewStage, Application)
        .join(Application, Application.id == InterviewStage.application_id)
        .where(Application.workspace_id == workspace.id)
    )
    if person_ids is not None:
        stmt = stmt.where(Application.person_id.in_(person_ids))
    if search and search.strip():
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                InterviewStage.name.ilike(term),
                Application.company_name.ilike(term),
                Application.job_title.ilike(term),
            )
        )

    # Most recently scheduled first: a follow-on round almost always attaches to
    # something that happened lately.
    rows = list(
        db.execute(
            stmt.order_by(
                InterviewStage.scheduled_start.desc().nullslast(),
                InterviewStage.sequence.desc(),
            ).limit(limit)
        )
    )
    if not rows:
        return []

    registry = load_registry(db, workspace.id)
    stage_ids = [stage.id for stage, _ in rows]

    counts = dict(
        db.execute(
            select(InterviewEvent.interview_stage_id, func.count(InterviewEvent.id))
            .where(InterviewEvent.interview_stage_id.in_(stage_ids))
            .group_by(InterviewEvent.interview_stage_id)
        ).all()
    )
    # One grouped query for the next round per application, never one per row.
    application_ids = {application.id for _, application in rows}
    highest = dict(
        db.execute(
            select(
                InterviewStage.application_id, func.max(InterviewStage.round_number)
            )
            .where(InterviewStage.application_id.in_(application_ids))
            .group_by(InterviewStage.application_id)
        ).all()
    )

    return [
        InterviewSearchResult(
            stage_id=stage.id,
            application_id=application.id,
            person_id=application.person_id,
            company_name=application.company_name,
            job_title=application.job_title,
            stage_name=stage.name,
            stage_badge=stage_badge(
                stage.round_number, registry.get(stage.type_key).short_label
            ),
            type_key=stage.type_key,
            round_number=stage.round_number,
            sequence=stage.sequence,
            status=stage.status,
            outcome=stage.outcome,
            scheduled_start=stage.scheduled_start,
            result_date=stage.result_date,
            event_count=int(counts.get(stage.id, 0)),
            next_round_number=int(highest.get(application.id) or 0) + 1,
        )
        for stage, application in rows
    ]


# --------------------------------------------------------------------------
# Stage CRUD
# --------------------------------------------------------------------------


def create_stage(
    db: Session,
    workspace: Workspace,
    application_id: str,
    payload: InterviewStageCreate,
    *,
    registry: TypeRegistry | None = None,
) -> InterviewStage:
    application = get_application(db, workspace, application_id)
    registry = registry or load_registry(db, workspace.id)
    type_key = _validate_type_key(db, workspace, payload.type_key)
    info = registry.get(type_key)

    round_number = payload.round_number
    if round_number is None and not info.counts_as_screening:
        # Screening rounds are usually not numbered; everything else is.
        round_number = _next_round_number(db, application.id)

    status = payload.status or InterviewStatus.PLANNED
    outcome = payload.outcome or InterviewOutcome.PENDING
    if payload.events:
        status = InterviewStatus.SCHEDULED if status is InterviewStatus.PLANNED else status
    status, outcome = normalise_status_outcome(status, outcome)

    stage = InterviewStage(
        application_id=application.id,
        round_number=round_number,
        sequence=payload.sequence
        if payload.sequence is not None
        else _next_sequence(db, application.id),
        name=(payload.name or default_stage_name(round_number, info.label)).strip(),
        type_key=type_key,
        status=status.value,
        outcome=outcome.value,
        result_date=payload.result_date,
        notes=payload.notes,
    )
    db.add(stage)
    db.flush()

    for index, event_payload in enumerate(payload.events):
        _create_event_row(db, stage, event_payload, sequence=index)
    db.flush()
    recompute_stage_window(stage)

    touch(application)
    person = db.get(Person, application.person_id)
    badge = stage_badge(stage.round_number, info.short_label)
    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.STAGE_CREATED,
        message=(
            f"{person.display_name if person else 'Someone'} added "
            f"{badge} for {application.company_name}"
        ),
        person_id=application.person_id,
        application_id=application.id,
        interview_stage_id=stage.id,
        meta={"badge": badge, "type": type_key},
    )
    _maybe_advance_application(db, workspace, application, stage, registry)
    db.commit()
    return stage


def update_stage(
    db: Session, workspace: Workspace, stage_id: str, payload: InterviewStageUpdate
) -> InterviewStage:
    stage = get_stage(db, workspace, stage_id)
    application = db.get(Application, stage.application_id)
    assert application is not None
    registry = load_registry(db, workspace.id)

    data = payload.model_dump(exclude_unset=True)
    previous_status = stage.status
    previous_outcome = stage.outcome
    previous_start = stage.scheduled_start

    if data.get("type_key"):
        stage.type_key = _validate_type_key(db, workspace, data["type_key"])
    if data.get("name"):
        stage.name = data["name"].strip()
    if "round_number" in data:
        stage.round_number = data["round_number"]
    if "sequence" in data and data["sequence"] is not None:
        stage.sequence = data["sequence"]
    if "notes" in data:
        stage.notes = data["notes"]
    if "result_date" in data:
        stage.result_date = data["result_date"]

    status = InterviewStatus(data.get("status") or stage.status)
    outcome = InterviewOutcome(data.get("outcome") or stage.outcome)
    status, outcome = normalise_status_outcome(status, outcome)
    stage.status = status.value
    stage.outcome = outcome.value

    _finalise_result_date(db, stage, application, previous_outcome)
    touch(application)

    _log_stage_changes(
        db,
        workspace,
        application,
        stage,
        registry,
        previous_status=previous_status,
        previous_outcome=previous_outcome,
        previous_start=previous_start,
    )
    _apply_followup_rules(db, workspace, application, stage, previous_outcome, previous_status)
    _maybe_advance_application(db, workspace, application, stage, registry)
    db.commit()
    return stage


def set_outcome(
    db: Session, workspace: Workspace, stage_id: str, payload: InterviewOutcomeUpdate
) -> InterviewStage:
    """The "How did it go?" flow (spec §49) — one tap, a few seconds."""
    stage = get_stage(db, workspace, stage_id)
    application = db.get(Application, stage.application_id)
    assert application is not None
    registry = load_registry(db, workspace.id)

    previous_status = stage.status
    previous_outcome = stage.outcome

    status = payload.status or InterviewStatus(stage.status)
    status, outcome = normalise_status_outcome(status, payload.outcome)
    stage.status = status.value
    stage.outcome = outcome.value
    if payload.result_date is not None:
        stage.result_date = payload.result_date
    if payload.note:
        stage.notes = f"{stage.notes}\n{payload.note}".strip() if stage.notes else payload.note

    _finalise_result_date(db, stage, application, previous_outcome)
    touch(application)

    _log_stage_changes(
        db,
        workspace,
        application,
        stage,
        registry,
        previous_status=previous_status,
        previous_outcome=previous_outcome,
        previous_start=stage.scheduled_start,
    )

    from app.domains.followups import rules as followup_rules
    from app.domains.followups import service as followup_service
    from app.schemas.followup import FollowUpCreate

    followup_rules.on_stage_outcome_changed(
        db, workspace, application, stage, previous_outcome, previous_status
    )

    if payload.create_follow_up:
        suggestion = followup_rules.suggest_after_interview(
            db, workspace, application, stage
        )
        if suggestion is not None:
            due = payload.follow_up_due_date or suggestion.suggested_due_date
            followup_service.create_follow_up(
                db,
                workspace,
                FollowUpCreate(
                    application_id=application.id,
                    interview_stage_id=stage.id,
                    title=suggestion.title,
                    reason=suggestion.reason,
                    due_date=due,
                ),
                auto_generated=True,
                rule_key=suggestion.rule_key,
                commit=False,
            )

    _maybe_advance_application(db, workspace, application, stage, registry)
    db.commit()
    return stage


def _finalise_result_date(
    db: Session, stage: InterviewStage, application: Application, previous_outcome: str
) -> None:
    """Stamp the day a verdict landed, so analytics can bucket it by period."""
    outcome = InterviewOutcome(stage.outcome)
    if outcome in DECIDED_OUTCOMES and stage.result_date is None:
        person = db.get(Person, application.person_id)
        stage.result_date = local_date(utcnow(), person.timezone if person else None)
    if outcome not in DECIDED_OUTCOMES and previous_outcome in {
        o.value for o in DECIDED_OUTCOMES
    }:
        # Verdict retracted — clear the date so it is not counted as decided.
        stage.result_date = None


def _log_stage_changes(
    db: Session,
    workspace: Workspace,
    application: Application,
    stage: InterviewStage,
    registry: TypeRegistry,
    *,
    previous_status: str,
    previous_outcome: str,
    previous_start: datetime | None,
) -> None:
    person = db.get(Person, application.person_id)
    name = person.display_name if person else "Someone"
    badge = stage_badge(stage.round_number, registry.short_label(stage.type_key))

    if stage.status != previous_status:
        activity_service.log(
            db,
            workspace_id=workspace.id,
            activity_type=ActivityType.STAGE_STATUS_CHANGED,
            message=(
                f"{name}'s {application.company_name} {badge} changed from "
                f"{_humanise(previous_status)} to {_humanise(stage.status)}"
            ),
            person_id=application.person_id,
            application_id=application.id,
            interview_stage_id=stage.id,
            meta={"from": previous_status, "to": stage.status, "badge": badge},
        )
    if stage.outcome != previous_outcome:
        activity_service.log(
            db,
            workspace_id=workspace.id,
            activity_type=ActivityType.STAGE_OUTCOME_CHANGED,
            message=(
                f"{application.company_name} {badge} outcome changed from "
                f"{_humanise(previous_outcome)} to {_humanise(stage.outcome)}"
            ),
            person_id=application.person_id,
            application_id=application.id,
            interview_stage_id=stage.id,
            meta={"from": previous_outcome, "to": stage.outcome, "badge": badge},
        )
    if (
        previous_start is not None
        and stage.scheduled_start is not None
        and previous_start != stage.scheduled_start
    ):
        activity_service.log(
            db,
            workspace_id=workspace.id,
            activity_type=ActivityType.STAGE_RESCHEDULED,
            message=(
                f"{application.company_name} {badge} moved from "
                f"{previous_start:%b %-d} to {stage.scheduled_start:%b %-d}"
            ),
            person_id=application.person_id,
            application_id=application.id,
            interview_stage_id=stage.id,
        )


def _humanise(value: str) -> str:
    return value.replace("_", " ").title()


def _apply_followup_rules(
    db: Session,
    workspace: Workspace,
    application: Application,
    stage: InterviewStage,
    previous_outcome: str,
    previous_status: str,
) -> None:
    from app.domains.followups import rules as followup_rules

    followup_rules.on_stage_outcome_changed(
        db, workspace, application, stage, previous_outcome, previous_status
    )


def _maybe_advance_application(
    db: Session,
    workspace: Workspace,
    application: Application,
    stage: InterviewStage,
    registry: TypeRegistry,
) -> None:
    """Nudge the application status forward as interviews progress (spec §63).

    Deliberately conservative: it only ever moves an application *forward* out
    of an early status, and never touches an application the user has already
    parked in a decided state (offer, rejected, ghosted, ...). The intent is to
    save admin, not to overrule a deliberate choice.
    """
    current = ApplicationStatus(application.status)
    early = {
        ApplicationStatus.SAVED,
        ApplicationStatus.APPLIED,
        ApplicationStatus.RECRUITER_CONTACTED,
        ApplicationStatus.SCREENING,
        ApplicationStatus.SCHEDULING_NEXT_ROUND,
    }
    info = registry.get(stage.type_key)
    target: ApplicationStatus | None = None

    if stage.status == InterviewStatus.SCHEDULED.value:
        if info.counts_as_final and current in early | {ApplicationStatus.INTERVIEWING}:
            target = ApplicationStatus.FINAL_ROUND
        elif info.counts_as_screening and current in {
            ApplicationStatus.SAVED,
            ApplicationStatus.APPLIED,
            ApplicationStatus.RECRUITER_CONTACTED,
        }:
            target = ApplicationStatus.SCREENING
        elif current in early:
            target = ApplicationStatus.INTERVIEWING
    elif stage.outcome == InterviewOutcome.WAITING.value and current in early | {
        ApplicationStatus.INTERVIEWING
    }:
        target = ApplicationStatus.WAITING_FOR_FEEDBACK

    if target is None or target.value == application.status:
        return

    previous = application.status
    application.status = target.value
    person = db.get(Person, application.person_id)
    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.APPLICATION_STATUS_CHANGED,
        message=(
            f"{person.display_name if person else 'Someone'}'s "
            f"{application.company_name} application moved from "
            f"{_humanise(previous)} to {_humanise(target.value)}"
        ),
        person_id=application.person_id,
        application_id=application.id,
        meta={"from": previous, "to": target.value, "automatic": True},
    )


def delete_stage(db: Session, workspace: Workspace, stage_id: str) -> None:
    stage = get_stage(db, workspace, stage_id)
    application = db.get(Application, stage.application_id)
    assert application is not None
    registry = load_registry(db, workspace.id)
    badge = stage_badge(stage.round_number, registry.short_label(stage.type_key))

    db.delete(stage)
    touch(application)
    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.STAGE_DELETED,
        message=f"{badge} was removed from {application.company_name}",
        person_id=application.person_id,
        application_id=application.id,
    )
    db.commit()


def reorder_stages(
    db: Session, workspace: Workspace, application_id: str, stage_ids: list[str]
) -> list[InterviewStage]:
    application = get_application(db, workspace, application_id)
    stages = {
        s.id: s
        for s in db.scalars(
            select(InterviewStage).where(
                InterviewStage.application_id == application.id
            )
        )
    }
    unknown = [sid for sid in stage_ids if sid not in stages]
    if unknown:
        raise ValidationError(
            "Those interviews do not belong to this application.",
            code="stage_mismatch",
            details={"unknown_ids": unknown},
        )
    for index, stage_id in enumerate(stage_ids):
        stages[stage_id].sequence = index + 1
    db.commit()
    return sorted(stages.values(), key=lambda s: s.sequence)


# --------------------------------------------------------------------------
# Event CRUD
# --------------------------------------------------------------------------


def _create_event_row(
    db: Session,
    stage: InterviewStage,
    payload: InterviewEventCreate,
    *,
    sequence: int = 0,
) -> InterviewEvent:
    ends_at = payload.ends_at or payload.starts_at + timedelta(minutes=DEFAULT_EVENT_MINUTES)
    event = InterviewEvent(
        interview_stage_id=stage.id,
        title=(payload.title or stage.name)[:512],
        type_key=payload.type_key,
        starts_at=payload.starts_at,
        ends_at=ends_at,
        timezone=payload.timezone,
        location=payload.location,
        meeting_url=payload.meeting_url,
        interviewer_names=payload.interviewer_names,
        sequence=sequence,
    )
    db.add(event)
    return event


def add_event(
    db: Session, workspace: Workspace, stage_id: str, payload: InterviewEventCreate
) -> InterviewEvent:
    stage = get_stage(db, workspace, stage_id)
    application = db.get(Application, stage.application_id)
    assert application is not None

    if payload.type_key:
        _validate_type_key(db, workspace, payload.type_key)

    next_seq = (
        db.scalar(
            select(func.max(InterviewEvent.sequence)).where(
                InterviewEvent.interview_stage_id == stage.id
            )
        )
        or 0
    ) + 1
    event = _create_event_row(db, stage, payload, sequence=next_seq)
    db.flush()
    db.refresh(stage)
    recompute_stage_window(stage)
    touch(application)

    if payload.add_to_calendar:
        from app.domains.calendar import writeback

        writeback.push_event(db, workspace, stage, event)

    db.commit()
    return event


def update_event(
    db: Session, workspace: Workspace, event_id: str, payload: InterviewEventUpdate
) -> InterviewEvent:
    event = db.get(InterviewEvent, event_id)
    if event is None:
        raise NotFoundError("That interview slot could not be found.", code="event_not_found")
    stage = get_stage(db, workspace, event.interview_stage_id)
    application = db.get(Application, stage.application_id)
    assert application is not None

    data = payload.model_dump(exclude_unset=True)
    if data.get("type_key"):
        _validate_type_key(db, workspace, data["type_key"])
        event.type_key = data["type_key"]

    for key in ("title", "timezone", "location", "meeting_url", "interviewer_names"):
        if key in data:
            setattr(event, key, data[key])

    if "starts_at" in data and data["starts_at"] is not None:
        duration = event.ends_at - event.starts_at
        event.starts_at = data["starts_at"]
        event.ends_at = data.get("ends_at") or event.starts_at + duration
    elif "ends_at" in data and data["ends_at"] is not None:
        event.ends_at = data["ends_at"]

    if event.ends_at <= event.starts_at:
        raise ValidationError(
            "The end time must be after the start time.", code="invalid_time_range"
        )

    db.flush()
    db.refresh(stage)
    recompute_stage_window(stage)
    touch(application)

    if payload.sync_to_calendar:
        from app.domains.calendar import writeback

        writeback.push_event(db, workspace, stage, event)

    db.commit()
    return event


def delete_event(db: Session, workspace: Workspace, event_id: str) -> None:
    event = db.get(InterviewEvent, event_id)
    if event is None:
        raise NotFoundError("That interview slot could not be found.", code="event_not_found")
    stage = get_stage(db, workspace, event.interview_stage_id)
    db.delete(event)
    db.flush()
    db.refresh(stage)
    recompute_stage_window(stage)
    db.commit()


# --------------------------------------------------------------------------
# Queries used by the dashboard and calendar
# --------------------------------------------------------------------------


def upcoming_interviews(
    db: Session,
    workspace: Workspace,
    person_ids: list[str],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 25,
    registry: TypeRegistry | None = None,
) -> list[UpcomingInterview]:
    """Chronological list of scheduled interview slots (spec §24).

    Returns one row per *event*, so a four-slot final loop shows all four —
    each of them is a thing the person has to turn up to.
    """
    if not person_ids:
        return []
    registry = registry or load_registry(db, workspace.id)
    start = start or utcnow()

    stmt = (
        select(InterviewEvent, InterviewStage, Application, Person)
        .join(InterviewStage, InterviewStage.id == InterviewEvent.interview_stage_id)
        .join(Application, Application.id == InterviewStage.application_id)
        .join(Person, Person.id == Application.person_id)
        .where(
            Application.person_id.in_(person_ids),
            Application.archived_at.is_(None),
            InterviewStage.status == InterviewStatus.SCHEDULED.value,
            InterviewEvent.starts_at >= start,
        )
        .order_by(InterviewEvent.starts_at.asc())
        .limit(limit)
    )
    if end is not None:
        stmt = stmt.where(InterviewEvent.starts_at < end)

    rows: list[UpcomingInterview] = []
    for event, stage, application, person in db.execute(stmt):
        info = registry.get(event.type_key or stage.type_key)
        rows.append(
            UpcomingInterview(
                stage_id=stage.id,
                event_id=event.id,
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
                starts_at=event.starts_at,
                ends_at=event.ends_at,
                timezone=event.timezone,
                meeting_url=event.meeting_url,
                location=event.location,
            )
        )
    return rows


def stages_awaiting_outcome(
    db: Session, workspace: Workspace, person_ids: list[str], *, now: datetime | None = None
) -> list[tuple[InterviewStage, Application, Person]]:
    """Scheduled interviews whose time has passed — these drive the
    "How did it go?" prompt (spec §49)."""
    if not person_ids:
        return []
    now = now or utcnow()
    stmt = (
        select(InterviewStage, Application, Person)
        .join(Application, Application.id == InterviewStage.application_id)
        .join(Person, Person.id == Application.person_id)
        .where(
            Application.person_id.in_(person_ids),
            Application.archived_at.is_(None),
            InterviewStage.status == InterviewStatus.SCHEDULED.value,
            InterviewStage.scheduled_end.is_not(None),
            InterviewStage.scheduled_end < now,
        )
        .order_by(InterviewStage.scheduled_end.desc())
    )
    return list(db.execute(stmt))


def list_stages(
    db: Session, workspace: Workspace, application_id: str
) -> list[InterviewStage]:
    application = get_application(db, workspace, application_id)
    return list(
        db.scalars(
            select(InterviewStage)
            .where(InterviewStage.application_id == application.id)
            .options(selectinload(InterviewStage.events))
            .order_by(InterviewStage.sequence, InterviewStage.created_at)
        )
    )


def business_day_suggestion(from_date: date, business_days: int) -> date:
    from app.core.timeutils import add_business_days

    return add_business_days(from_date, business_days)
