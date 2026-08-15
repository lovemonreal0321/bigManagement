"""Email account management."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import encrypt
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.security import create_state_token, decode_state_token
from app.core.timeutils import utcnow
from app.domains.calendar.providers.http import request
from app.domains.email.providers import get_email_adapter
from app.domains.email.providers.gmail import GMAIL_SCOPES, TOKEN_URL
from app.domains.email.providers.imap import KNOWN_HOSTS, suggest_host
from app.domains.email.providers.microsoft import OUTLOOK_MAIL_SCOPES
from app.enums import ConnectionStatus, EmailProvider
from app.models import EmailAccount, Person, Workspace
from app.schemas.email import (
    EmailAccountOut,
    EmailAccountUpdate,
    EmailProviderInfo,
    ImapAccountCreate,
    ImapHostSuggestion,
)

logger = logging.getLogger(__name__)


def list_providers() -> list[EmailProviderInfo]:
    missing = []
    if not settings.google_client_id:
        missing.append("GOOGLE_CLIENT_ID")
    if not settings.google_client_secret:
        missing.append("GOOGLE_CLIENT_SECRET")

    microsoft_missing = []
    if not settings.microsoft_client_id:
        microsoft_missing.append("MICROSOFT_CLIENT_ID")
    if not settings.microsoft_client_secret:
        microsoft_missing.append("MICROSOFT_CLIENT_SECRET")

    return [
        EmailProviderInfo(
            key=EmailProvider.GMAIL.value,
            display_name="Gmail",
            is_configured=settings.google_configured,
            requires_app_password=False,
            missing_settings=missing,
            setup_hint=(
                None
                if settings.google_configured
                else (
                    f"Set {', '.join(missing)} in backend/.env and enable the Gmail "
                    "API in the same Google Cloud project as Calendar."
                )
            ),
        ),
        EmailProviderInfo(
            key=EmailProvider.MICROSOFT.value,
            display_name="Outlook",
            is_configured=settings.microsoft_configured,
            requires_app_password=False,
            missing_settings=microsoft_missing,
            setup_hint=(
                None
                if settings.microsoft_configured
                else (
                    f"Set {', '.join(microsoft_missing)} in backend/.env and add "
                    "the Mail.Read delegated permission to the same Azure app "
                    "registration used for Calendar."
                )
            ),
        ),
        EmailProviderInfo(
            key=EmailProvider.IMAP.value,
            display_name="Yahoo / IMAP",
            # IMAP needs nothing server-side; the credentials are per-account.
            is_configured=True,
            requires_app_password=True,
            setup_hint=(
                "Yahoo grants mail OAuth only to pre-approved partner apps, so "
                "it connects over IMAP with an app-specific password (Yahoo "
                "Account Security → Generate app password). Note that "
                "Microsoft 365 work accounts cannot use IMAP at all — connect "
                "those with Outlook above."
            ),
        ),
    ]


def suggest_imap_settings(address: str) -> ImapHostSuggestion:
    host, port, folders = suggest_host(address)
    domain = address.rsplit("@", 1)[-1].lower() if "@" in address else ""
    known = domain in KNOWN_HOSTS
    hint = None
    if known and "yahoo" in (host or ""):
        hint = (
            "Yahoo requires an app password — generate one at "
            "Account Security → Generate app password."
        )
    elif not known:
        hint = "Unknown provider: enter the IMAP server address manually."
    return ImapHostSuggestion(
        host=host, port=port, folders=folders, known_provider=known, hint=hint
    )


def account_to_out(account: EmailAccount, person: Person | None) -> EmailAccountOut:
    adapter = get_email_adapter(account.provider)
    out = EmailAccountOut.model_validate(account)
    out.provider_display_name = adapter.display_name
    if person is not None:
        out.person_name = person.display_name
        out.person_color = person.color
        out.person_initials = person.initials
    return out


def list_accounts(
    db: Session, workspace: Workspace, person_ids: list[str] | None = None
) -> list[EmailAccountOut]:
    stmt = (
        select(EmailAccount, Person)
        .join(Person, Person.id == EmailAccount.person_id)
        .where(Person.workspace_id == workspace.id)
        .order_by(Person.sort_order, Person.name)
    )
    if person_ids is not None:
        stmt = stmt.where(EmailAccount.person_id.in_(person_ids))
    return [account_to_out(account, person) for account, person in db.execute(stmt)]


def get_account(db: Session, workspace: Workspace, account_id: str) -> EmailAccount:
    account = db.get(EmailAccount, account_id)
    if account is None:
        raise NotFoundError("That mailbox could not be found.", code="email_account_not_found")
    person = db.get(Person, account.person_id)
    if person is None or person.workspace_id != workspace.id:
        raise NotFoundError("That mailbox could not be found.", code="email_account_not_found")
    return account


# --------------------------------------------------------------------------
# IMAP accounts
# --------------------------------------------------------------------------


def create_imap_account(
    db: Session, workspace: Workspace, payload: ImapAccountCreate
) -> EmailAccount:
    person = db.get(Person, payload.person_id)
    if person is None or person.workspace_id != workspace.id:
        raise ValidationError("Unknown person.", code="person_not_found")

    address = str(payload.address).lower()
    existing = db.scalars(
        select(EmailAccount).where(
            EmailAccount.person_id == person.id,
            EmailAccount.provider == EmailProvider.IMAP.value,
            EmailAccount.address == address,
        )
    ).first()
    if existing is not None:
        raise ConflictError(
            f"{address} is already connected for {person.display_name}.",
            code="email_account_exists",
        )

    host, port, folders = suggest_host(address)
    host = payload.imap_host or host
    if not host:
        raise ValidationError(
            "Enter the IMAP server address for this provider.", code="imap_host_required"
        )

    if settings.secret_key_is_ephemeral:
        # The password is encrypted with a key derived from SECRET_KEY. If that
        # is regenerated at boot, this account breaks on the next restart —
        # better to refuse than to store something that silently rots.
        raise ValidationError(
            "Set a fixed SECRET_KEY in backend/.env before connecting a mailbox. "
            "App passwords are encrypted with a key derived from it, and a "
            "regenerated key cannot decrypt them after a restart.",
            code="secret_key_ephemeral",
        )

    account = EmailAccount(
        person_id=person.id,
        provider=EmailProvider.IMAP.value,
        address=address,
        display_name=person.display_name,
        imap_host=host,
        imap_port=payload.imap_port or port,
        imap_username=payload.imap_username or address,
        imap_password_encrypted=encrypt(payload.password),
        imap_use_ssl=payload.imap_use_ssl,
        imap_folders=payload.folders or folders,
        status=ConnectionStatus.CONNECTED.value,
    )
    db.add(account)
    db.flush()

    # Prove it works now rather than failing silently at the first enrichment.
    adapter = get_email_adapter(EmailProvider.IMAP.value)
    try:
        adapter.verify(account)
    except Exception:
        db.rollback()
        raise

    account.last_used_at = utcnow()
    db.commit()
    return account


def update_account(
    db: Session, workspace: Workspace, account_id: str, payload: EmailAccountUpdate
) -> EmailAccount:
    account = get_account(db, workspace, account_id)
    data = payload.model_dump(exclude_unset=True)

    if "display_name" in data:
        account.display_name = data["display_name"]
    if data.get("imap_host"):
        account.imap_host = data["imap_host"]
    if data.get("imap_port"):
        account.imap_port = data["imap_port"]
    if data.get("folders") is not None:
        account.imap_folders = data["folders"]
    if data.get("password"):
        account.imap_password_encrypted = encrypt(data["password"])
        account.status = ConnectionStatus.CONNECTED.value
        account.last_error = None

    db.flush()
    if account.provider == EmailProvider.IMAP.value:
        get_email_adapter(account.provider).verify(account)
    db.commit()
    return account


def verify_account(db: Session, workspace: Workspace, account_id: str) -> EmailAccount:
    account = get_account(db, workspace, account_id)
    adapter = get_email_adapter(account.provider)
    try:
        adapter.verify(account)
        account.status = ConnectionStatus.CONNECTED.value
        account.last_error = None
        account.last_error_at = None
        account.last_used_at = utcnow()
    except Exception as exc:
        account.status = ConnectionStatus.ERROR.value
        account.last_error = (getattr(exc, "message", None) or str(exc))[:500]
        account.last_error_at = utcnow()
        db.commit()
        raise
    db.commit()
    return account


def delete_account(db: Session, workspace: Workspace, account_id: str) -> None:
    account = get_account(db, workspace, account_id)
    db.delete(account)
    db.commit()


# --------------------------------------------------------------------------
# Gmail OAuth
# --------------------------------------------------------------------------


def gmail_authorization_url(
    db: Session, workspace: Workspace, person_id: str
) -> str:
    from urllib.parse import urlencode

    person = db.get(Person, person_id)
    if person is None or person.workspace_id != workspace.id:
        raise ValidationError("Unknown person.", code="person_not_found")
    if not settings.google_configured:
        from app.core.errors import ProviderNotConfiguredError

        raise ProviderNotConfiguredError(
            "Gmail needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in "
            "backend/.env, and the Gmail API enabled in the same Google Cloud "
            "project as Calendar.",
            details={"missing": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]},
        )

    state = create_state_token({"person_id": person.id, "kind": "gmail"})
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.gmail_redirect_uri,
        "response_type": "code",
        "scope": " ".join(GMAIL_SCOPES),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def complete_gmail_oauth(
    db: Session, workspace: Workspace, *, state: str, code: str
) -> EmailAccount:
    from datetime import timedelta

    claims = decode_state_token(state)
    if not claims or claims.get("kind") != "gmail":
        raise ValidationError(
            "That sign-in link expired. Please start the connection again.",
            code="invalid_oauth_state",
        )

    person = db.get(Person, claims.get("person_id", ""))
    if person is None or person.workspace_id != workspace.id:
        raise ValidationError("Unknown person.", code="person_not_found")

    tokens = request(
        "POST",
        TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.gmail_redirect_uri,
            "grant_type": "authorization_code",
        },
        provider="gmail",
    )
    profile = request(
        "GET",
        "https://www.googleapis.com/oauth2/v3/userinfo",
        access_token=tokens["access_token"],
        provider="gmail",
    )
    address = (profile.get("email") or "").lower()
    if not address:
        raise ValidationError(
            "Google did not return an email address for that account.",
            code="gmail_no_address",
        )

    account = db.scalars(
        select(EmailAccount).where(
            EmailAccount.person_id == person.id,
            EmailAccount.provider == EmailProvider.GMAIL.value,
            EmailAccount.address == address,
        )
    ).first()
    if account is None:
        account = EmailAccount(
            person_id=person.id,
            provider=EmailProvider.GMAIL.value,
            address=address,
        )
        db.add(account)

    account.display_name = profile.get("name") or person.display_name
    account.access_token = tokens["access_token"]
    if tokens.get("refresh_token"):
        account.refresh_token = tokens["refresh_token"]
    expires_in = tokens.get("expires_in")
    account.token_expires_at = (
        utcnow() + timedelta(seconds=int(expires_in)) if expires_in else None
    )
    account.scope = tokens.get("scope")
    account.status = ConnectionStatus.CONNECTED.value
    account.last_error = None
    db.commit()
    return account


# --------------------------------------------------------------------------
# Outlook OAuth
# --------------------------------------------------------------------------


def outlook_authorization_url(
    db: Session, workspace: Workspace, person_id: str
) -> str:
    from urllib.parse import urlencode

    from app.domains.calendar.providers.microsoft import _authority

    person = db.get(Person, person_id)
    if person is None or person.workspace_id != workspace.id:
        raise ValidationError("Unknown person.", code="person_not_found")
    if not settings.microsoft_configured:
        from app.core.errors import ProviderNotConfiguredError

        raise ProviderNotConfiguredError(
            "Outlook mail needs MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET "
            "in backend/.env, and the Mail.Read delegated permission on the "
            "same Azure app registration used for Calendar.",
            details={"missing": ["MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"]},
        )

    state = create_state_token({"person_id": person.id, "kind": "outlook"})
    params = {
        "client_id": settings.microsoft_client_id,
        "response_type": "code",
        "redirect_uri": settings.outlook_mail_redirect_uri,
        "response_mode": "query",
        "scope": " ".join(OUTLOOK_MAIL_SCOPES),
        "state": state,
    }
    return f"{_authority()}/oauth2/v2.0/authorize?{urlencode(params)}"


def complete_outlook_oauth(
    db: Session, workspace: Workspace, *, state: str, code: str
) -> EmailAccount:
    from datetime import timedelta

    from app.domains.calendar.providers.microsoft import GRAPH, _authority

    claims = decode_state_token(state)
    if not claims or claims.get("kind") != "outlook":
        raise ValidationError(
            "That sign-in link expired. Please start the connection again.",
            code="invalid_oauth_state",
        )

    person = db.get(Person, claims.get("person_id", ""))
    if person is None or person.workspace_id != workspace.id:
        raise ValidationError("Unknown person.", code="person_not_found")

    tokens = request(
        "POST",
        f"{_authority()}/oauth2/v2.0/token",
        data={
            "client_id": settings.microsoft_client_id,
            "client_secret": settings.microsoft_client_secret,
            "code": code,
            "redirect_uri": settings.outlook_mail_redirect_uri,
            "grant_type": "authorization_code",
            "scope": " ".join(OUTLOOK_MAIL_SCOPES),
        },
        provider="outlook",
    )
    profile = request(
        "GET", f"{GRAPH}/me", access_token=tokens["access_token"], provider="outlook"
    )
    address = (profile.get("mail") or profile.get("userPrincipalName") or "").lower()
    if not address:
        raise ValidationError(
            "Microsoft did not return an email address for that account.",
            code="outlook_no_address",
        )

    account = db.scalars(
        select(EmailAccount).where(
            EmailAccount.person_id == person.id,
            EmailAccount.provider == EmailProvider.MICROSOFT.value,
            EmailAccount.address == address,
        )
    ).first()
    if account is None:
        account = EmailAccount(
            person_id=person.id,
            provider=EmailProvider.MICROSOFT.value,
            address=address,
        )
        db.add(account)

    account.display_name = profile.get("displayName") or person.display_name
    account.access_token = tokens["access_token"]
    if tokens.get("refresh_token"):
        account.refresh_token = tokens["refresh_token"]
    expires_in = tokens.get("expires_in")
    account.token_expires_at = (
        utcnow() + timedelta(seconds=int(expires_in)) if expires_in else None
    )
    account.scope = tokens.get("scope")
    account.status = ConnectionStatus.CONNECTED.value
    account.last_error = None
    db.commit()
    return account
