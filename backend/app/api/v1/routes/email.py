"""Email account + AI enrichment endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import CurrentWorkspace, DbSession, SelectedPeople
from app.core.errors import AppError
from app.domains.ai import enrichment as ai_enrichment
from app.domains.ai import service as ai_service
from app.domains.auth.service import get_workspace
from app.domains.email import service as email_service
from app.schemas.calendar import OAuthStartOut
from app.schemas.common import OkResponse
from app.schemas.email import (
    AiExtractionOut,
    AiStatusOut,
    EmailAccountOut,
    EmailAccountUpdate,
    EmailProviderInfo,
    EnrichRequest,
    EnrichSummary,
    ImapAccountCreate,
    ImapHostSuggestion,
)

router = APIRouter(prefix="/email", tags=["email"])
ai_router = APIRouter(prefix="/ai", tags=["ai"])


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------


@router.get("/providers", response_model=list[EmailProviderInfo])
def list_email_providers() -> list[EmailProviderInfo]:
    return email_service.list_providers()


@router.get("/accounts", response_model=list[EmailAccountOut])
def list_accounts(
    db: DbSession, workspace: CurrentWorkspace
) -> list[EmailAccountOut]:
    return email_service.list_accounts(db, workspace, None)


@router.get("/imap/suggest", response_model=ImapHostSuggestion)
def suggest_imap(address: Annotated[str, Query()]) -> ImapHostSuggestion:
    """Prefill the IMAP form from an address (Yahoo, iCloud, Outlook, …)."""
    return email_service.suggest_imap_settings(address)


@router.post("/accounts/imap", response_model=EmailAccountOut, status_code=201)
def create_imap_account(
    payload: ImapAccountCreate, db: DbSession, workspace: CurrentWorkspace
) -> EmailAccountOut:
    account = email_service.create_imap_account(db, workspace, payload)
    from app.models import Person

    return email_service.account_to_out(account, db.get(Person, account.person_id))


@router.patch("/accounts/{account_id}", response_model=EmailAccountOut)
def update_account(
    account_id: str,
    payload: EmailAccountUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> EmailAccountOut:
    account = email_service.update_account(db, workspace, account_id, payload)
    from app.models import Person

    return email_service.account_to_out(account, db.get(Person, account.person_id))


@router.post("/accounts/{account_id}/verify", response_model=EmailAccountOut)
def verify_account(
    account_id: str, db: DbSession, workspace: CurrentWorkspace
) -> EmailAccountOut:
    account = email_service.verify_account(db, workspace, account_id)
    from app.models import Person

    return email_service.account_to_out(account, db.get(Person, account.person_id))


@router.delete("/accounts/{account_id}", response_model=OkResponse)
def delete_account(
    account_id: str, db: DbSession, workspace: CurrentWorkspace
) -> OkResponse:
    email_service.delete_account(db, workspace, account_id)
    return OkResponse(message="Mailbox disconnected.")


# --------------------------------------------------------------------------
# Gmail OAuth
# --------------------------------------------------------------------------


@router.post("/oauth/google/start", response_model=OAuthStartOut)
def start_gmail_oauth(
    person_id: Annotated[str, Query()], db: DbSession, workspace: CurrentWorkspace
) -> OAuthStartOut:
    return OAuthStartOut(
        authorization_url=email_service.gmail_authorization_url(db, workspace, person_id)
    )


@router.get("/oauth/google/callback", include_in_schema=False)
def gmail_oauth_callback(
    state: str | None = None, code: str | None = None, error: str | None = None
) -> RedirectResponse:
    """Google redirect target for the Gmail scope.

    Unauthenticated for the same reason as the calendar callback: the browser
    arrives straight from Google. Trust comes from the signed `state`.
    """
    redirect_base = f"{settings.frontend_url}/settings"
    if error:
        return RedirectResponse(f"{redirect_base}?email_error={error}", status_code=302)
    if not state or not code:
        return RedirectResponse(
            f"{redirect_base}?email_error=missing_code", status_code=302
        )

    db = next(get_db())
    try:
        workspace = get_workspace(db)
        email_service.complete_gmail_oauth(db, workspace, state=state, code=code)
        return RedirectResponse(f"{redirect_base}?email_connected=gmail", status_code=302)
    except AppError as exc:
        return RedirectResponse(f"{redirect_base}?email_error={exc.code}", status_code=302)
    finally:
        db.close()


# --------------------------------------------------------------------------
# AI
# --------------------------------------------------------------------------


@ai_router.get("/status", response_model=AiStatusOut)
def ai_status(db: DbSession, workspace: CurrentWorkspace) -> AiStatusOut:
    return ai_service.status(db, workspace)


@ai_router.get("/extractions", response_model=list[AiExtractionOut])
def list_extractions(
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
    status: Annotated[list[str] | None, Query()] = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[AiExtractionOut]:
    """The "Created by AI" review feed."""
    return ai_service.list_extractions(
        db, workspace, scope.ids, statuses=status, limit=limit
    )


@ai_router.get("/extractions/{extraction_id}", response_model=AiExtractionOut)
def get_extraction(
    extraction_id: str, db: DbSession, workspace: CurrentWorkspace
) -> AiExtractionOut:
    """One extraction plus the emails it read, so the reasoning is inspectable."""
    return ai_service.get_extraction(db, workspace, extraction_id)


@ai_router.post("/enrich", response_model=EnrichSummary)
def enrich(
    payload: EnrichRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: SelectedPeople,
) -> EnrichSummary:
    """Read email for calendar events that look like interviews, and fill in
    the application and round from what it finds."""
    return ai_service.run_enrichment(
        db,
        workspace,
        person_ids=scope.ids,
        calendar_event_ids=payload.calendar_event_ids or None,
        force=payload.force,
        limit=payload.limit,
    )


@ai_router.post("/extractions/{extraction_id}/undo", response_model=AiExtractionOut)
def undo_extraction(
    extraction_id: str, db: DbSession, workspace: CurrentWorkspace
) -> AiExtractionOut:
    """Reverse exactly what this extraction created."""
    ai_enrichment.undo(db, workspace, extraction_id)
    return ai_service.get_extraction(db, workspace, extraction_id)


@ai_router.post("/extractions/{extraction_id}/apply", response_model=AiExtractionOut)
def apply_extraction(
    extraction_id: str, db: DbSession, workspace: CurrentWorkspace
) -> AiExtractionOut:
    """Accept a suggestion that fell below the auto-create threshold."""
    ai_enrichment.apply_suggestion(db, workspace, extraction_id)
    return ai_service.get_extraction(db, workspace, extraction_id)
