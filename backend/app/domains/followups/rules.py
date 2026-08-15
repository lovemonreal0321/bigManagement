"""Follow-up automation rules (spec §20, §21).

Design constraint from the spec: *suggest*, do not silently generate. Rules
here fall into two groups.

**Suggestions** (`suggest_*`) return a proposal the UI renders with
accept / modify / dismiss buttons. Nothing is written to the database.

**Reactions** (`on_*`) fire inside an existing transaction when something
changes, and only ever *close* follow-ups that have been overtaken by events.
Closing a stale task is not the same as inventing new work, so it does not
need a prompt.

Every automatic follow-up carries a `rule_key`, which doubles as the dedupe
key — a rule that already produced an open item for a stage will not produce
a second one.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutils import add_business_days, local_date, utcnow
from app.enums import (
    DECIDED_OUTCOMES,
    OFFER_STATUSES,
    ApplicationStatus,
    FollowUpRule,
    FollowUpStatus,
    InterviewOutcome,
    InterviewStatus,
)
from app.models import Application, FollowUp, InterviewStage, Person, Workspace
from app.schemas.followup import FollowUpSuggestion


def _today_for(db: Session, application: Application) -> date:
    person = db.get(Person, application.person_id)
    return local_date(utcnow(), person.timezone if person else None)


def _has_open_rule_followup(
    db: Session, *, application_id: str, stage_id: str | None, rule_key: str
) -> bool:
    stmt = select(FollowUp.id).where(
        FollowUp.application_id == application_id,
        FollowUp.rule_key == rule_key,
        FollowUp.status.in_([FollowUpStatus.OPEN.value, FollowUpStatus.SNOOZED.value]),
    )
    if stage_id is not None:
        stmt = stmt.where(FollowUp.interview_stage_id == stage_id)
    return db.scalar(stmt.limit(1)) is not None


# --------------------------------------------------------------------------
# Suggestions
# --------------------------------------------------------------------------


def suggest_after_interview(
    db: Session, workspace: Workspace, application: Application, stage: InterviewStage
) -> FollowUpSuggestion | None:
    """Rule: interview completed -> follow up in N business days (spec §20).

    Only applies while the result is still outstanding. Once the stage has a
    verdict there is nothing to chase.
    """
    if stage.status not in (InterviewStatus.COMPLETED.value, InterviewStatus.NO_SHOW.value):
        return None
    if stage.outcome in {o.value for o in DECIDED_OUTCOMES}:
        return None
    if _has_open_rule_followup(
        db,
        application_id=application.id,
        stage_id=stage.id,
        rule_key=FollowUpRule.INTERVIEW_COMPLETED.value,
    ):
        return None

    # Count business days from the interview itself, not from "now" — marking
    # an outcome a week late should not push the follow-up a week out.
    anchor = (
        local_date(stage.scheduled_end, None)
        if stage.scheduled_end is not None
        else _today_for(db, application)
    )
    due = add_business_days(anchor, workspace.followup_after_interview_business_days)

    return FollowUpSuggestion(
        rule_key=FollowUpRule.INTERVIEW_COMPLETED.value,
        application_id=application.id,
        interview_stage_id=stage.id,
        person_id=application.person_id,
        title=f"Follow up on {application.company_name} — {stage.name}",
        reason=(
            f"{stage.name} was completed and there is no result yet. "
            f"{workspace.followup_after_interview_business_days} business days "
            "is a reasonable time to check in."
        ),
        suggested_due_date=due,
    )


def suggest_after_follow_up(
    db: Session, workspace: Workspace, follow_up: FollowUp
) -> FollowUpSuggestion | None:
    """Rule: follow-up completed -> optionally chain another (spec §21).

    Suppressed once the application has reached an offer or a terminal state,
    where continuing to chase would be noise.
    """
    application = db.get(Application, follow_up.application_id)
    if application is None:
        return None
    status = ApplicationStatus(application.status)
    if status in OFFER_STATUSES or status in {
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.ACCEPTED,
        ApplicationStatus.ARCHIVED,
    }:
        return None
    if _has_open_rule_followup(
        db,
        application_id=application.id,
        stage_id=None,
        rule_key=FollowUpRule.FOLLOW_UP_CHAIN.value,
    ):
        return None

    today = _today_for(db, application)
    return FollowUpSuggestion(
        rule_key=FollowUpRule.FOLLOW_UP_CHAIN.value,
        application_id=application.id,
        interview_stage_id=follow_up.interview_stage_id,
        person_id=application.person_id,
        title=f"Check in again with {application.company_name}",
        reason="The previous follow-up was completed and there is still no answer.",
        suggested_due_date=add_business_days(
            today, workspace.followup_chain_business_days
        ),
    )


def collect_suggestions(
    db: Session, workspace: Workspace, person_ids: list[str], *, limit: int = 25
) -> list[FollowUpSuggestion]:
    """Every currently-applicable follow-up suggestion for the selected people."""
    if not person_ids:
        return []

    rows = db.execute(
        select(InterviewStage, Application)
        .join(Application, Application.id == InterviewStage.application_id)
        .where(
            Application.person_id.in_(person_ids),
            Application.archived_at.is_(None),
            Application.status.not_in([s.value for s in OFFER_STATUSES]),
            InterviewStage.status.in_(
                [InterviewStatus.COMPLETED.value, InterviewStatus.NO_SHOW.value]
            ),
            InterviewStage.outcome.not_in([o.value for o in DECIDED_OUTCOMES]),
        )
        .order_by(InterviewStage.scheduled_end.desc())
        .limit(limit * 2)
    )

    suggestions: list[FollowUpSuggestion] = []
    for stage, application in rows:
        suggestion = suggest_after_interview(db, workspace, application, stage)
        if suggestion is not None:
            suggestions.append(suggestion)
        if len(suggestions) >= limit:
            break
    return suggestions


# --------------------------------------------------------------------------
# Reactions
# --------------------------------------------------------------------------


def _close_open(
    db: Session, follow_ups: list[FollowUp], *, reason: str
) -> int:
    closed = 0
    for follow_up in follow_ups:
        if follow_up.status in (FollowUpStatus.OPEN.value, FollowUpStatus.SNOOZED.value):
            follow_up.status = FollowUpStatus.COMPLETED.value
            follow_up.completed_at = utcnow()
            follow_up.notes = (
                f"{follow_up.notes}\n{reason}".strip() if follow_up.notes else reason
            )
            closed += 1
    return closed


def on_stage_outcome_changed(
    db: Session,
    workspace: Workspace,
    application: Application,
    stage: InterviewStage,
    previous_outcome: str,
    previous_status: str,
) -> None:
    """Close follow-ups that the new state has made pointless.

    * A verdict arrived -> the "chase this result" task is done.
    * A new interview got scheduled -> the "get the next round booked" task is
      done (spec §21).
    """
    if stage.outcome == previous_outcome and stage.status == previous_status:
        return

    if stage.outcome in {o.value for o in DECIDED_OUTCOMES}:
        stage_follow_ups = list(
            db.scalars(
                select(FollowUp).where(
                    FollowUp.interview_stage_id == stage.id,
                    FollowUp.status.in_(
                        [FollowUpStatus.OPEN.value, FollowUpStatus.SNOOZED.value]
                    ),
                )
            )
        )
        _close_open(
            db,
            stage_follow_ups,
            reason=f"Closed automatically — result recorded as {stage.outcome}.",
        )

    if (
        stage.status == InterviewStatus.SCHEDULED.value
        and previous_status != InterviewStatus.SCHEDULED.value
    ):
        chained = list(
            db.scalars(
                select(FollowUp).where(
                    FollowUp.application_id == application.id,
                    FollowUp.rule_key == FollowUpRule.FOLLOW_UP_CHAIN.value,
                    FollowUp.status.in_(
                        [FollowUpStatus.OPEN.value, FollowUpStatus.SNOOZED.value]
                    ),
                )
            )
        )
        _close_open(
            db, chained, reason="Closed automatically — the next round is scheduled."
        )


def on_application_status_changed(
    db: Session, workspace: Workspace, application: Application, previous_status: str
) -> None:
    """Rule: an offer (or a closed application) retires outstanding chasing."""
    status = ApplicationStatus(application.status)
    terminal = status in OFFER_STATUSES or status in {
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.ARCHIVED,
        ApplicationStatus.GHOSTED,
    }
    if not terminal:
        return

    open_items = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.application_id == application.id,
                FollowUp.status.in_(
                    [FollowUpStatus.OPEN.value, FollowUpStatus.SNOOZED.value]
                ),
            )
        )
    )
    if status in OFFER_STATUSES:
        reason = "Closed automatically — an offer was received."
    else:
        reason = f"Closed automatically — application marked {status.value}."
    _close_open(db, open_items, reason=reason)


def on_stage_scheduled(
    db: Session, workspace: Workspace, application: Application, stage: InterviewStage
) -> None:
    """Rule: interview scheduled -> close the outdated "schedule next round"
    follow-up (spec §21)."""
    open_items = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.application_id == application.id,
                FollowUp.auto_generated.is_(True),
                FollowUp.status.in_(
                    [FollowUpStatus.OPEN.value, FollowUpStatus.SNOOZED.value]
                ),
            )
        )
    )
    _close_open(
        db, open_items, reason=f"Closed automatically — {stage.name} is scheduled."
    )


def interview_outcome_is_open(stage: InterviewStage) -> bool:
    """Helper used by the Needs Attention panel."""
    return (
        stage.status == InterviewStatus.COMPLETED.value
        and stage.outcome
        in (InterviewOutcome.WAITING.value, InterviewOutcome.PENDING.value)
    )
