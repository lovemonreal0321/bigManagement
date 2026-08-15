"""Follow-up CRUD and the bucketed board (spec §19, §31)."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.core.timeutils import local_date, utcnow
from app.domains.activity import service as activity_service
from app.domains.applications.service import get_application, touch
from app.domains.followups.status import compute_state, describe
from app.domains.interviews.types import TypeRegistry, load_registry, stage_badge
from app.enums import (
    ActivityType,
    FollowUpComputedStatus,
    FollowUpRule,
    FollowUpStatus,
)
from app.models import Application, FollowUp, InterviewStage, Person, Workspace
from app.schemas.followup import (
    FollowUpBoard,
    FollowUpCreate,
    FollowUpOut,
    FollowUpUpdate,
)


def get_follow_up(db: Session, workspace: Workspace, follow_up_id: str) -> FollowUp:
    follow_up = db.get(FollowUp, follow_up_id)
    if follow_up is None:
        raise NotFoundError(
            "That follow-up could not be found.", code="follow_up_not_found"
        )
    application = db.get(Application, follow_up.application_id)
    if application is None or application.workspace_id != workspace.id:
        raise NotFoundError(
            "That follow-up could not be found.", code="follow_up_not_found"
        )
    return follow_up


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------


def to_out(
    follow_up: FollowUp,
    *,
    person: Person | None,
    application: Application | None,
    stage: InterviewStage | None,
    registry: TypeRegistry,
    today: date | None = None,
) -> FollowUpOut:
    day = today or local_date(utcnow(), person.timezone if person else None)
    state = compute_state(
        stored_status=follow_up.status,
        due_date=follow_up.due_date,
        today=day,
        snoozed_until=follow_up.snoozed_until,
    )
    out = FollowUpOut.model_validate(
        {
            **{
                field: getattr(follow_up, field)
                for field in FollowUpOut.model_fields
                if hasattr(follow_up, field)
            },
            "computed_status": state.status.value,
        }
    )
    out.days_overdue = state.days_overdue
    out.days_until_due = state.days_until_due
    out.due_description = describe(state)
    if person is not None:
        out.person_name = person.display_name
        out.person_color = person.color
        out.person_initials = person.initials
    if application is not None:
        out.company_name = application.company_name
        out.job_title = application.job_title
    if stage is not None:
        out.stage_badge = stage_badge(
            stage.round_number, registry.short_label(stage.type_key)
        )
    return out


def _hydrate(
    db: Session, workspace: Workspace, follow_ups: list[FollowUp]
) -> list[FollowUpOut]:
    """Batch-load the context every card needs (spec §56 — no N+1)."""
    if not follow_ups:
        return []
    registry = load_registry(db, workspace.id)

    person_ids = {f.person_id for f in follow_ups}
    app_ids = {f.application_id for f in follow_ups}
    stage_ids = {f.interview_stage_id for f in follow_ups if f.interview_stage_id}

    people = {p.id: p for p in db.scalars(select(Person).where(Person.id.in_(person_ids)))}
    apps = {
        a.id: a for a in db.scalars(select(Application).where(Application.id.in_(app_ids)))
    }
    stages = (
        {
            s.id: s
            for s in db.scalars(
                select(InterviewStage).where(InterviewStage.id.in_(stage_ids))
            )
        }
        if stage_ids
        else {}
    )

    now = utcnow()
    return [
        to_out(
            follow_up,
            person=people.get(follow_up.person_id),
            application=apps.get(follow_up.application_id),
            stage=stages.get(follow_up.interview_stage_id or ""),
            registry=registry,
            today=local_date(
                now,
                people[follow_up.person_id].timezone
                if follow_up.person_id in people
                else None,
            ),
        )
        for follow_up in follow_ups
    ]


# --------------------------------------------------------------------------
# Queries
# --------------------------------------------------------------------------


def list_follow_ups(
    db: Session,
    workspace: Workspace,
    person_ids: list[str],
    *,
    statuses: list[str] | None = None,
    application_id: str | None = None,
    limit: int = 200,
) -> list[FollowUpOut]:
    if not person_ids:
        return []
    stmt = select(FollowUp).where(FollowUp.person_id.in_(person_ids))
    if statuses:
        stmt = stmt.where(FollowUp.status.in_(statuses))
    if application_id:
        stmt = stmt.where(FollowUp.application_id == application_id)
    stmt = stmt.order_by(FollowUp.due_date.asc(), FollowUp.created_at.asc()).limit(limit)
    return _hydrate(db, workspace, list(db.scalars(stmt)))


def build_board(
    db: Session, workspace: Workspace, person_ids: list[str], *, completed_limit: int = 25
) -> FollowUpBoard:
    """The Follow-Ups page, bucketed by computed status."""
    if not person_ids:
        return FollowUpBoard(counts={})

    open_items = _hydrate(
        db,
        workspace,
        list(
            db.scalars(
                select(FollowUp)
                .where(
                    FollowUp.person_id.in_(person_ids),
                    FollowUp.status.in_(
                        [FollowUpStatus.OPEN.value, FollowUpStatus.SNOOZED.value]
                    ),
                )
                .order_by(FollowUp.due_date.asc())
            )
        ),
    )
    completed = _hydrate(
        db,
        workspace,
        list(
            db.scalars(
                select(FollowUp)
                .where(
                    FollowUp.person_id.in_(person_ids),
                    FollowUp.status == FollowUpStatus.COMPLETED.value,
                )
                .order_by(FollowUp.completed_at.desc())
                .limit(completed_limit)
            )
        ),
    )

    board = FollowUpBoard(completed=completed)
    for item in open_items:
        match item.computed_status:
            case FollowUpComputedStatus.OVERDUE.value:
                board.overdue.append(item)
            case FollowUpComputedStatus.DUE_TODAY.value:
                board.due_today.append(item)
            case FollowUpComputedStatus.SNOOZED.value:
                board.snoozed.append(item)
            case _:
                board.upcoming.append(item)

    board.counts = {
        "overdue": len(board.overdue),
        "due_today": len(board.due_today),
        "upcoming": len(board.upcoming),
        "snoozed": len(board.snoozed),
        "completed": len(board.completed),
    }
    return board


# --------------------------------------------------------------------------
# Mutations
# --------------------------------------------------------------------------


def create_follow_up(
    db: Session,
    workspace: Workspace,
    payload: FollowUpCreate,
    *,
    auto_generated: bool = False,
    rule_key: str = FollowUpRule.MANUAL.value,
    commit: bool = True,
) -> FollowUp:
    application = get_application(db, workspace, payload.application_id)

    stage_id = payload.interview_stage_id
    if stage_id:
        stage = db.get(InterviewStage, stage_id)
        if stage is None or stage.application_id != application.id:
            raise ValidationError(
                "That interview does not belong to this application.",
                code="stage_mismatch",
            )

    follow_up = FollowUp(
        person_id=application.person_id,
        application_id=application.id,
        interview_stage_id=stage_id,
        title=payload.title.strip(),
        reason=payload.reason,
        due_date=payload.due_date,
        due_time=payload.due_time,
        priority=payload.priority.value,
        notes=payload.notes,
        auto_generated=auto_generated,
        rule_key=rule_key,
    )
    db.add(follow_up)
    db.flush()
    touch(application)

    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.FOLLOW_UP_CREATED,
        message=f"Follow-up created for {application.company_name}: {follow_up.title}",
        person_id=application.person_id,
        application_id=application.id,
        interview_stage_id=stage_id,
        follow_up_id=follow_up.id,
    )
    if commit:
        db.commit()
    return follow_up


def update_follow_up(
    db: Session, workspace: Workspace, follow_up_id: str, payload: FollowUpUpdate
) -> FollowUp:
    follow_up = get_follow_up(db, workspace, follow_up_id)
    data = payload.model_dump(exclude_unset=True)

    for key in ("title", "reason", "due_date", "due_time", "notes"):
        if key in data:
            setattr(follow_up, key, data[key])
    if "priority" in data and data["priority"] is not None:
        follow_up.priority = data["priority"].value
    if "interview_stage_id" in data:
        follow_up.interview_stage_id = data["interview_stage_id"]

    if "status" in data and data["status"] is not None:
        new_status = data["status"].value
        if new_status == FollowUpStatus.COMPLETED.value:
            return complete_follow_up(db, workspace, follow_up_id)
        follow_up.status = new_status
        if new_status != FollowUpStatus.SNOOZED.value:
            follow_up.snoozed_until = None

    db.commit()
    return follow_up


def complete_follow_up(
    db: Session, workspace: Workspace, follow_up_id: str
) -> FollowUp:
    follow_up = get_follow_up(db, workspace, follow_up_id)
    if follow_up.status != FollowUpStatus.COMPLETED.value:
        follow_up.status = FollowUpStatus.COMPLETED.value
        follow_up.completed_at = utcnow()
        follow_up.snoozed_until = None

        application = db.get(Application, follow_up.application_id)
        if application is not None:
            touch(application)
            activity_service.log(
                db,
                workspace_id=workspace.id,
                activity_type=ActivityType.FOLLOW_UP_COMPLETED,
                message=(
                    f"Follow-up completed for {application.company_name}: "
                    f"{follow_up.title}"
                ),
                person_id=follow_up.person_id,
                application_id=follow_up.application_id,
                follow_up_id=follow_up.id,
            )
        db.commit()
    return follow_up


def snooze_follow_up(
    db: Session,
    workspace: Workspace,
    follow_up_id: str,
    *,
    until: date | None = None,
    days: int | None = None,
) -> FollowUp:
    follow_up = get_follow_up(db, workspace, follow_up_id)
    person = db.get(Person, follow_up.person_id)
    today = local_date(utcnow(), person.timezone if person else None)

    if until is None:
        until = today + timedelta(days=days or 1)
    if until <= today:
        raise ValidationError(
            "Choose a snooze date in the future.", code="invalid_snooze_date"
        )

    follow_up.status = FollowUpStatus.SNOOZED.value
    follow_up.snoozed_until = until
    # Keep the due date in step, so an un-snoozed item is not instantly overdue.
    if follow_up.due_date < until:
        follow_up.due_date = until

    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.FOLLOW_UP_SNOOZED,
        message=f"Follow-up snoozed until {until:%b %-d}: {follow_up.title}",
        person_id=follow_up.person_id,
        application_id=follow_up.application_id,
        follow_up_id=follow_up.id,
    )
    db.commit()
    return follow_up


def cancel_follow_up(db: Session, workspace: Workspace, follow_up_id: str) -> FollowUp:
    follow_up = get_follow_up(db, workspace, follow_up_id)
    if follow_up.status != FollowUpStatus.CANCELLED.value:
        follow_up.status = FollowUpStatus.CANCELLED.value
        activity_service.log(
            db,
            workspace_id=workspace.id,
            activity_type=ActivityType.FOLLOW_UP_CANCELLED,
            message=f"Follow-up cancelled: {follow_up.title}",
            person_id=follow_up.person_id,
            application_id=follow_up.application_id,
            follow_up_id=follow_up.id,
        )
        db.commit()
    return follow_up


def delete_follow_up(db: Session, workspace: Workspace, follow_up_id: str) -> None:
    follow_up = get_follow_up(db, workspace, follow_up_id)
    db.delete(follow_up)
    db.commit()


def hydrate_one(db: Session, workspace: Workspace, follow_up: FollowUp) -> FollowUpOut:
    return _hydrate(db, workspace, [follow_up])[0]
