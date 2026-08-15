"""AI review feed and batch enrichment."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timeutils import utcnow
from app.domains.ai import enrichment, kimi
from app.domains.interviews.types import load_registry, stage_badge
from app.enums import EventClassification, ExtractionStatus
from app.models import (
    AiExtraction,
    Application,
    CalendarEvent,
    EmailAccount,
    EmailMessage,
    InterviewStage,
    Person,
    Workspace,
)
from app.schemas.email import (
    AiExtractionOut,
    AiStatusOut,
    EmailMessageOut,
    EnrichSummary,
)

logger = logging.getLogger(__name__)

#: Events scoring at least this are worth spending a model call on.
CANDIDATE_DETECTION_SCORE = 0.5


def status(db: Session, workspace: Workspace) -> AiStatusOut:
    account_count = len(
        list(
            db.scalars(
                select(EmailAccount.id)
                .join(Person, Person.id == EmailAccount.person_id)
                .where(Person.workspace_id == workspace.id)
            )
        )
    )
    configured = kimi.is_configured()
    hint = None
    if not settings.ai_enabled:
        hint = "AI is switched off (AI_ENABLED=false in backend/.env)."
    elif not settings.kimi_api_key:
        hint = (
            "Add KIMI_API_KEY to backend/.env from platform.moonshot.ai, then "
            "restart. Keys from the .cn platform need KIMI_BASE_URL changed too."
        )
    elif account_count == 0:
        hint = "Connect a mailbox below so the AI has emails to read."

    return AiStatusOut(
        enabled=settings.ai_enabled,
        configured=configured,
        model=settings.kimi_model,
        base_url=settings.kimi_base_url,
        auto_create_confidence=settings.ai_auto_create_confidence,
        email_accounts=account_count,
        setup_hint=hint,
    )


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------


def to_out(
    db: Session, extraction: AiExtraction, *, include_messages: bool = False
) -> AiExtractionOut:
    out = AiExtractionOut.model_validate(extraction)
    out.is_undoable = extraction.is_undoable

    person = db.get(Person, extraction.person_id or "")
    if person is not None:
        out.person_name = person.display_name
        out.person_color = person.color
        out.person_initials = person.initials

    if extraction.calendar_event_id:
        event = db.get(CalendarEvent, extraction.calendar_event_id)
        if event is not None:
            out.event_title = event.title
            out.event_starts_at = event.starts_at

    result = extraction.result or {}
    out.company_name = result.get("company")
    out.job_title = result.get("role")

    if extraction.created_stage_id:
        stage = db.get(InterviewStage, extraction.created_stage_id)
        if stage is not None:
            registry = load_registry(db, extraction.workspace_id)
            out.stage_badge = stage_badge(
                stage.round_number, registry.short_label(stage.type_key)
            )
            application = db.get(Application, stage.application_id)
            if application is not None:
                out.company_name = application.company_name
                out.job_title = application.job_title

    if include_messages and extraction.calendar_event_id:
        messages = db.scalars(
            select(EmailMessage)
            .where(EmailMessage.calendar_event_id == extraction.calendar_event_id)
            .order_by(EmailMessage.sent_at.desc())
        )
        out.messages = [EmailMessageOut.model_validate(m) for m in messages]

    return out


def list_extractions(
    db: Session,
    workspace: Workspace,
    person_ids: list[str],
    *,
    statuses: list[str] | None = None,
    limit: int = 50,
) -> list[AiExtractionOut]:
    """The "Created by AI" feed."""
    if not person_ids:
        return []
    stmt = select(AiExtraction).where(
        AiExtraction.workspace_id == workspace.id,
        AiExtraction.person_id.in_(person_ids),
    )
    if statuses:
        stmt = stmt.where(AiExtraction.status.in_(statuses))
    else:
        # Failures and "not an interview" are noise in the review feed.
        stmt = stmt.where(
            AiExtraction.status.in_(
                [
                    ExtractionStatus.APPLIED.value,
                    ExtractionStatus.SUGGESTED.value,
                    ExtractionStatus.UNDONE.value,
                ]
            )
        )
    stmt = stmt.order_by(AiExtraction.created_at.desc()).limit(limit)
    return [to_out(db, extraction) for extraction in db.scalars(stmt)]


def get_extraction(
    db: Session, workspace: Workspace, extraction_id: str
) -> AiExtractionOut:
    from app.core.errors import NotFoundError

    extraction = db.get(AiExtraction, extraction_id)
    if extraction is None or extraction.workspace_id != workspace.id:
        raise NotFoundError("That AI action could not be found.", code="extraction_not_found")
    return to_out(db, extraction, include_messages=True)


# --------------------------------------------------------------------------
# Batch enrichment
# --------------------------------------------------------------------------


def candidate_events(
    db: Session, workspace: Workspace, person_ids: list[str], *, limit: int = 10
) -> list[CalendarEvent]:
    """Events worth spending a model call on.

    Either the heuristics flagged them, or a human already said "interview".
    Anything already enriched is skipped, and past events beyond the window are
    not worth backfilling automatically.
    """
    if not person_ids:
        return []

    done = select(AiExtraction.calendar_event_id).where(
        AiExtraction.calendar_event_id.is_not(None)
    )
    horizon = utcnow() - timedelta(days=settings.email_lookback_days)

    stmt = (
        select(CalendarEvent)
        .where(
            CalendarEvent.person_id.in_(person_ids),
            CalendarEvent.deleted_at.is_(None),
            CalendarEvent.starts_at >= horizon,
            CalendarEvent.id.not_in(done),
            (CalendarEvent.detection_score >= CANDIDATE_DETECTION_SCORE)
            | (CalendarEvent.classification == EventClassification.INTERVIEW.value),
        )
        .order_by(CalendarEvent.starts_at.asc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def run_enrichment(
    db: Session,
    workspace: Workspace,
    *,
    person_ids: list[str],
    calendar_event_ids: list[str] | None = None,
    force: bool = False,
    limit: int = 10,
) -> EnrichSummary:
    summary = EnrichSummary()

    if calendar_event_ids:
        events = list(
            db.scalars(
                select(CalendarEvent).where(CalendarEvent.id.in_(calendar_event_ids))
            )
        )
    else:
        events = candidate_events(db, workspace, person_ids, limit=limit)

    if not events:
        return summary

    if not kimi.is_configured():
        summary.errors.append(
            "AI enrichment is not configured. Add KIMI_API_KEY to backend/.env."
        )
        return summary

    for event in events:
        try:
            extraction = enrichment.enrich_event(db, workspace, event, force=force)
        except Exception as exc:
            logger.exception("enrichment failed for event %s", event.id)
            summary.failed += 1
            summary.errors.append((getattr(exc, "message", None) or str(exc))[:200])
            continue

        summary.processed += 1
        summary.tokens_used += extraction.tokens_used
        match extraction.status:
            case ExtractionStatus.APPLIED.value:
                summary.applied += 1
            case ExtractionStatus.SUGGESTED.value:
                summary.suggested += 1
            case ExtractionStatus.FAILED.value:
                summary.failed += 1
                if extraction.error:
                    summary.errors.append(extraction.error)
            case _:
                summary.skipped += 1

        if extraction.status in (
            ExtractionStatus.APPLIED.value,
            ExtractionStatus.SUGGESTED.value,
        ):
            summary.extractions.append(to_out(db, extraction))

    # Duplicate provider errors add nothing.
    summary.errors = list(dict.fromkeys(summary.errors))[:5]
    return summary
