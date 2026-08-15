"""Calendar-triggered enrichment.

The flow, end to end:

    calendar event that looks like an interview
      -> find the emails tied to THAT event (participants + time window)
      -> ask Kimi what interview this is
      -> create or extend the application and interview stage
      -> record exactly what was created, so it can be undone

The calendar is always the trigger. Nothing here discovers an application from
mail alone, and nothing runs over a mailbox that has no matching event.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.core.timeutils import local_date, utcnow
from app.domains.activity import service as activity_service
from app.domains.ai import kimi
from app.domains.ai.extraction import ExtractionResult, parse_result
from app.domains.ai.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    ExtractionSource,
    build_user_prompt,
)
from app.domains.email import matching
from app.domains.email.providers import get_email_adapter
from app.domains.interviews.types import default_stage_name, load_registry
from app.enums import (
    ActivityType,
    ApplicationStatus,
    ConnectionStatus,
    EventClassification,
    EventSource,
    ExtractionStatus,
    InterviewStatus,
    InterviewTypeKey,
)
from app.models import (
    AiExtraction,
    Application,
    CalendarEvent,
    EmailAccount,
    EmailMessage,
    InterviewEvent,
    InterviewStage,
    Person,
    Workspace,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Email gathering
# --------------------------------------------------------------------------


def gather_messages(
    db: Session, event: CalendarEvent, person: Person
) -> list[EmailMessage]:
    """Find and persist the emails related to one calendar event.

    Failures on a single mailbox are recorded on the account and skipped —
    one broken IMAP password should not stop enrichment from the other
    account.
    """
    accounts = list(
        db.scalars(
            select(EmailAccount).where(
                EmailAccount.person_id == person.id,
                EmailAccount.status != ConnectionStatus.DISCONNECTED.value,
            )
        )
    )
    if not accounts:
        return []

    query = matching.build_query(event, person)
    if not query.participants and not query.domains:
        # Nobody external on the invite: there is nothing to search *for*, and
        # a query without a counterparty would match the whole mailbox.
        return []

    stored: list[EmailMessage] = []
    for account in accounts:
        adapter = get_email_adapter(account.provider)
        try:
            fetched = adapter.search(account, query)
            account.last_used_at = utcnow()
            account.last_error = None
            account.status = ConnectionStatus.CONNECTED.value
        except Exception as exc:
            message = getattr(exc, "message", None) or str(exc)
            logger.warning("email search failed for %s: %s", account.address, message)
            account.last_error = message[:500]
            account.last_error_at = utcnow()
            account.status = ConnectionStatus.ERROR.value
            continue

        selected = matching.select_messages(
            fetched, event, query.participants, query.domains
        )
        for scored in selected:
            row = _upsert_message(db, account, event, scored)
            stored.append(row)

    db.flush()
    # Newest first: the most recent mail usually states the current round.
    stored.sort(key=lambda m: m.sent_at or utcnow() - timedelta(days=3650), reverse=True)
    return stored[: settings.email_max_messages_per_event]


def _upsert_message(
    db: Session,
    account: EmailAccount,
    event: CalendarEvent,
    scored: matching.ScoredMessage,
) -> EmailMessage:
    existing = db.scalars(
        select(EmailMessage).where(
            EmailMessage.account_id == account.id,
            EmailMessage.provider_message_id == scored.message.provider_message_id,
        )
    ).first()

    excerpt = (scored.message.body or "")[: settings.email_body_excerpt_chars]
    if existing is not None:
        existing.calendar_event_id = event.id
        existing.match_score = scored.score
        existing.match_reasons = scored.reasons
        existing.body_excerpt = excerpt
        return existing

    row = EmailMessage(
        account_id=account.id,
        calendar_event_id=event.id,
        provider_message_id=scored.message.provider_message_id,
        thread_id=scored.message.thread_id,
        subject=scored.message.subject,
        from_address=scored.message.from_address,
        from_name=scored.message.from_name,
        to_addresses=scored.message.to_addresses,
        sent_at=scored.message.sent_at,
        body_excerpt=excerpt,
        match_reasons=scored.reasons,
        match_score=scored.score,
    )
    db.add(row)
    return row


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


def _known_companies(db: Session, person: Person) -> list[str]:
    return [
        name
        for name in db.scalars(
            select(Application.company_name)
            .where(Application.person_id == person.id)
            .distinct()
            .order_by(Application.company_name)
        )
    ]


def build_source(
    db: Session, event: CalendarEvent, person: Person, messages: list[EmailMessage]
) -> ExtractionSource:
    return ExtractionSource(
        event_title=event.title,
        event_start=event.starts_at.isoformat(),
        event_end=event.ends_at.isoformat(),
        event_location=event.location or event.meeting_url,
        event_description=event.description,
        organizer=event.organizer_email,
        attendees=[
            str(a.get("email"))
            for a in (event.attendees or [])
            if isinstance(a, dict) and a.get("email")
        ],
        person_name=person.display_name,
        person_email=person.email,
        messages=[
            {
                "date": m.sent_at.isoformat() if m.sent_at else "unknown",
                "from": f"{m.from_name or ''} <{m.from_address or 'unknown'}>".strip(),
                "subject": m.subject or "(no subject)",
                "body": m.body_excerpt or "",
            }
            for m in messages
        ],
        known_companies=_known_companies(db, person),
    )


def enrich_event(
    db: Session,
    workspace: Workspace,
    event: CalendarEvent,
    *,
    force: bool = False,
    auto_apply: bool = True,
) -> AiExtraction:
    """Run the whole pipeline for one calendar event.

    Idempotent per event: an event already enriched is returned untouched
    unless `force` is set.
    """
    existing = db.scalars(
        select(AiExtraction).where(AiExtraction.calendar_event_id == event.id)
    ).first()
    if existing is not None and not force:
        return existing

    person = db.get(Person, event.person_id)
    if person is None:
        raise NotFoundError("That event has no person.", code="person_not_found")

    extraction = existing or AiExtraction(
        workspace_id=workspace.id,
        person_id=person.id,
        calendar_event_id=event.id,
    )
    if existing is None:
        db.add(extraction)
    extraction.prompt_version = PROMPT_VERSION
    extraction.error = None
    extraction.undone_at = None

    messages = gather_messages(db, event, person)
    extraction.message_count = len(messages)

    if not kimi.is_configured():
        extraction.status = ExtractionStatus.FAILED.value
        extraction.error = (
            "AI enrichment is not configured. Add KIMI_API_KEY to backend/.env."
        )
        db.commit()
        return extraction

    source = build_source(db, event, person, messages)
    try:
        response = kimi.complete(
            system=SYSTEM_PROMPT, user=build_user_prompt(source)
        )
        payload = response.json()
    except Exception as exc:
        extraction.status = ExtractionStatus.FAILED.value
        extraction.error = (getattr(exc, "message", None) or str(exc))[:500]
        db.commit()
        return extraction

    result = parse_result(payload)
    extraction.model = response.model
    extraction.tokens_used = response.tokens_used
    extraction.confidence = result.confidence
    extraction.result = result.to_dict()
    extraction.reasoning = result.reasoning
    extraction.status = ExtractionStatus.EXTRACTED.value

    if not result.is_interview:
        # The model says this is not an interview — record that and stop. The
        # event keeps its classification; a human can still override.
        extraction.status = ExtractionStatus.NO_MATCHES.value
        db.commit()
        return extraction

    if not auto_apply or not result.is_actionable:
        extraction.status = ExtractionStatus.SUGGESTED.value
        db.commit()
        return extraction

    if result.confidence < settings.ai_auto_create_confidence:
        # Confident enough to show, not confident enough to write.
        extraction.status = ExtractionStatus.SUGGESTED.value
        db.commit()
        return extraction

    apply_extraction(db, workspace, extraction, event, person, result)
    db.commit()
    return extraction


# --------------------------------------------------------------------------
# Applying
# --------------------------------------------------------------------------


def _normalise_company(name: str) -> str:
    cleaned = name.lower().strip()
    for suffix in (" inc.", " inc", " llc", " ltd.", " ltd", " gmbh", " corp.", " corp", ".com"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    return " ".join(cleaned.split())


def find_application(
    db: Session, person: Person, company: str
) -> Application | None:
    """Match an existing application by company, tolerantly.

    Exact (case-insensitive) first, then a normalised comparison, so "Acme" and
    "Acme Inc." do not become two applications.
    """
    candidates = list(
        db.scalars(
            select(Application)
            .where(Application.person_id == person.id, Application.archived_at.is_(None))
            .order_by(Application.last_activity_at.desc())
        )
    )
    target = _normalise_company(company)
    for application in candidates:
        if application.company_name.lower() == company.lower():
            return application
    for application in candidates:
        if _normalise_company(application.company_name) == target:
            return application
    return None


def apply_extraction(
    db: Session,
    workspace: Workspace,
    extraction: AiExtraction,
    event: CalendarEvent,
    person: Person,
    result: ExtractionResult,
) -> AiExtraction:
    """Create or extend records from a validated extraction."""
    if not result.company:  # pragma: no cover - guarded by is_actionable
        raise ValidationError("No company to apply.", code="ai_no_company")

    registry = load_registry(db, workspace.id)
    type_key = result.interview_type or InterviewTypeKey.OTHER.value
    if type_key not in registry.keys:
        type_key = InterviewTypeKey.OTHER.value
    info = registry.get(type_key)

    application = find_application(db, person, result.company)
    linked_existing = application is not None

    if application is None:
        # Date the application from the earliest related email if there is one:
        # that is when contact actually started.
        earliest = db.scalar(
            select(func.min(EmailMessage.sent_at)).where(
                EmailMessage.calendar_event_id == event.id
            )
        )
        applied_on = local_date(earliest or event.starts_at, person.timezone)
        application = Application(
            workspace_id=workspace.id,
            person_id=person.id,
            company_name=result.company,
            job_title=result.role or "Role not specified",
            location=result.location_or_link if result.location_or_link and "http" not in (result.location_or_link or "") else None,
            source="AI (calendar + email)",
            applied_date=applied_on,
            status=ApplicationStatus.INTERVIEWING.value,
            notes=result.next_steps,
            last_activity_at=utcnow(),
        )
        db.add(application)
        db.flush()
        extraction.created_application_id = application.id
    else:
        # Fill a blank role rather than overwriting anything the user set.
        if result.role and application.job_title in ("", "Role not specified"):
            application.job_title = result.role
        application.last_activity_at = utcnow()

    stage = _create_stage(db, application, event, result, type_key, info.label)
    extraction.created_stage_id = stage.id
    extraction.linked_existing_application = linked_existing
    extraction.status = ExtractionStatus.APPLIED.value

    # The event is now known to be an interview, and locked so the next sync's
    # heuristics do not second-guess it.
    event.classification = EventClassification.INTERVIEW.value
    event.classification_locked = True

    badge = f"R{stage.round_number} · {info.short_label}" if stage.round_number else info.short_label
    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.STAGE_CREATED,
        message=(
            f"AI added {badge} for {application.company_name} from "
            f"{extraction.message_count} email"
            f"{'s' if extraction.message_count != 1 else ''} and the calendar"
        ),
        person_id=person.id,
        application_id=application.id,
        interview_stage_id=stage.id,
        meta={"ai": True, "extraction_id": extraction.id, "confidence": result.confidence},
    )
    return extraction


def _create_stage(
    db: Session,
    application: Application,
    event: CalendarEvent,
    result: ExtractionResult,
    type_key: str,
    type_label: str,
) -> InterviewStage:
    sequence = (
        db.scalar(
            select(func.max(InterviewStage.sequence)).where(
                InterviewStage.application_id == application.id
            )
        )
        or 0
    ) + 1

    round_number = result.round_number
    if round_number is None:
        # The model could not establish the round from evidence. Fall back to
        # position in this application's own sequence, which is at least true
        # of the data we hold.
        existing_rounds = db.scalar(
            select(func.max(InterviewStage.round_number)).where(
                InterviewStage.application_id == application.id
            )
        )
        round_number = (existing_rounds or 0) + 1

    stage = InterviewStage(
        application_id=application.id,
        round_number=round_number,
        sequence=sequence,
        name=result.stage_name or default_stage_name(round_number, type_label),
        type_key=type_key,
        status=InterviewStatus.SCHEDULED.value,
        scheduled_start=event.starts_at,
        scheduled_end=event.ends_at,
        notes=_stage_notes(result),
    )
    db.add(stage)
    db.flush()

    db.add(
        InterviewEvent(
            interview_stage_id=stage.id,
            calendar_event_id=event.id,
            title=event.title[:512],
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            timezone=event.start_timezone,
            location=event.location,
            meeting_url=event.meeting_url,
            interviewer_names=", ".join(result.interviewers) or None,
            # It came from the provider, so write-back must never touch it.
            source=EventSource.EXTERNAL_PROVIDER.value,
        )
    )
    db.flush()
    return stage


def _stage_notes(result: ExtractionResult) -> str | None:
    parts = []
    if result.interviewers:
        parts.append(f"Interviewers: {', '.join(result.interviewers)}")
    if result.next_steps:
        parts.append(f"Next steps: {result.next_steps}")
    if result.salary_mentioned:
        parts.append(f"Compensation mentioned: {result.salary_mentioned}")
    return "\n".join(parts) or None


# --------------------------------------------------------------------------
# Undo
# --------------------------------------------------------------------------


def undo(db: Session, workspace: Workspace, extraction_id: str) -> AiExtraction:
    """Reverse exactly what an extraction created — and nothing more.

    A stage is always removed. The application is removed only if this
    extraction created it; if it merely added a round to an application that
    already existed, that application is left alone.
    """
    extraction = db.get(AiExtraction, extraction_id)
    if extraction is None or extraction.workspace_id != workspace.id:
        raise NotFoundError("That AI action could not be found.", code="extraction_not_found")
    if extraction.undone_at is not None:
        return extraction

    company = (extraction.result or {}).get("company") or "the application"

    if extraction.created_stage_id:
        stage = db.get(InterviewStage, extraction.created_stage_id)
        if stage is not None:
            db.delete(stage)  # cascades to its interview events

    if extraction.created_application_id and not extraction.linked_existing_application:
        application = db.get(Application, extraction.created_application_id)
        if application is not None:
            db.delete(application)

    # Hand the event back to manual triage.
    if extraction.calendar_event_id:
        event = db.get(CalendarEvent, extraction.calendar_event_id)
        if event is not None:
            event.classification = EventClassification.UNCLASSIFIED.value
            event.classification_locked = False
            # Do not immediately re-suggest something the user just rejected.
            event.detection_dismissed = True

    extraction.undone_at = utcnow()
    extraction.status = ExtractionStatus.UNDONE.value
    extraction.created_application_id = None
    extraction.created_stage_id = None

    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.STAGE_DELETED,
        message=f"Undid the AI-created interview for {company}",
        person_id=extraction.person_id,
        meta={"ai": True, "undo": True},
    )
    db.commit()
    return extraction


def apply_suggestion(
    db: Session, workspace: Workspace, extraction_id: str
) -> AiExtraction:
    """Accept a suggestion that was below the auto-create threshold."""
    extraction = db.get(AiExtraction, extraction_id)
    if extraction is None or extraction.workspace_id != workspace.id:
        raise NotFoundError("That AI action could not be found.", code="extraction_not_found")
    if extraction.status == ExtractionStatus.APPLIED.value:
        return extraction
    if not extraction.result:
        raise ValidationError("There is nothing to apply.", code="extraction_empty")

    event = db.get(CalendarEvent, extraction.calendar_event_id or "")
    person = db.get(Person, extraction.person_id or "")
    if event is None or person is None:
        raise NotFoundError("The original event is no longer available.", code="event_missing")

    result = parse_result(extraction.result)
    if not result.is_actionable:
        raise ValidationError(
            "This extraction does not have enough detail to create an application.",
            code="extraction_not_actionable",
        )
    apply_extraction(db, workspace, extraction, event, person, result)
    db.commit()
    return extraction
