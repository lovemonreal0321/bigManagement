"""Outlook / Microsoft 365 mail adapter (Microsoft Graph v1.0, read-only).

Chosen over IMAP for Microsoft accounts deliberately: Exchange Online disabled
basic authentication, so an app password over IMAP fails outright on work and
school accounts. Graph is OAuth throughout and behaves the same for personal
outlook.com and managed M365 mailboxes.

Unlike Yahoo — which only grants mail OAuth to pre-approved partner apps —
Microsoft lets any registered Azure application request `Mail.Read`, so this
works with credentials you create yourself.

Reuses the same Azure app registration as the calendar adapter; the only
difference is the extra scope.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from app.core.config import settings
from app.core.errors import CalendarConnectionExpiredError, ProviderNotConfiguredError
from app.core.timeutils import UTC, utcnow
from app.domains.calendar.providers.http import request
from app.domains.calendar.providers.microsoft import _authority
from app.domains.email.providers.base import (
    EmailProviderAdapter,
    EmailQuery,
    FetchedMessage,
)
from app.enums import ConnectionStatus, EmailProvider
from app.models import EmailAccount

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"

#: Read-only. The app never sends, deletes or modifies mail.
OUTLOOK_MAIL_SCOPES = [
    "openid",
    "email",
    "profile",
    "offline_access",
    "User.Read",
    "Mail.Read",
]


class OutlookAdapter(EmailProviderAdapter):
    key = EmailProvider.MICROSOFT.value
    display_name = "Outlook"

    def is_configured(self, account: EmailAccount) -> bool:
        return bool(settings.microsoft_configured and account.refresh_token)

    # -- tokens ------------------------------------------------------------

    def access_token(self, account: EmailAccount) -> str:
        if not settings.microsoft_configured:
            raise ProviderNotConfiguredError(
                "Outlook mail needs MICROSOFT_CLIENT_ID and "
                "MICROSOFT_CLIENT_SECRET in the backend .env file.",
                details={"missing": ["MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"]},
            )

        fresh = (
            account.access_token
            and account.token_expires_at is not None
            and account.token_expires_at - timedelta(minutes=5) > utcnow()
        )
        if fresh:
            return account.access_token  # type: ignore[return-value]

        if not account.refresh_token:
            account.status = ConnectionStatus.EXPIRED.value
            raise CalendarConnectionExpiredError(
                f"The Outlook connection for {account.address} expired. "
                "Please reconnect the account.",
                code="email_connection_expired",
            )

        payload = request(
            "POST",
            f"{_authority()}/oauth2/v2.0/token",
            data={
                "client_id": settings.microsoft_client_id,
                "client_secret": settings.microsoft_client_secret,
                "refresh_token": account.refresh_token,
                "grant_type": "refresh_token",
                "scope": " ".join(OUTLOOK_MAIL_SCOPES),
            },
            provider="outlook",
        )
        account.access_token = payload["access_token"]
        if payload.get("refresh_token"):
            account.refresh_token = payload["refresh_token"]
        expires_in = payload.get("expires_in")
        account.token_expires_at = (
            utcnow() + timedelta(seconds=int(expires_in)) if expires_in else None
        )
        account.status = ConnectionStatus.CONNECTED.value
        return account.access_token

    # -- operations --------------------------------------------------------

    def verify(self, account: EmailAccount) -> str:
        profile = request(
            "GET",
            f"{GRAPH}/me",
            access_token=self.access_token(account),
            provider="outlook",
        )
        return str(
            profile.get("mail") or profile.get("userPrincipalName") or account.address
        )

    def search(self, account: EmailAccount, query: EmailQuery) -> list[FetchedMessage]:
        if not query.participants and not query.domains:
            return []

        token = self.access_token(account)
        collected: dict[str, FetchedMessage] = {}

        # One KQL search per counterparty, unioned. `participants:` covers
        # from, to and cc in a single term, which $filter cannot do without
        # separate lambda expressions per field.
        needles = list(query.participants) + list(query.domains)
        for needle in needles:
            if len(collected) >= query.limit:
                break
            try:
                payload = request(
                    "GET",
                    f"{GRAPH}/me/messages",
                    access_token=token,
                    params={
                        "$search": f'"participants:{needle}"',
                        "$top": 50,
                        "$select": (
                            "id,conversationId,subject,from,toRecipients,"
                            "ccRecipients,receivedDateTime,bodyPreview,body"
                        ),
                    },
                    provider="outlook",
                )
            except Exception as exc:
                logger.warning("outlook search failed for %r: %s", needle, exc)
                continue

            for item in payload.get("value", []):
                message = _parse_message(item)
                if message is None or message.provider_message_id in collected:
                    continue
                # $search cannot be combined with $filter or $orderby, so the
                # window is applied here instead.
                if not _within(message.sent_at, query):
                    continue
                collected[message.provider_message_id] = message
                if len(collected) >= query.limit:
                    break

        messages = list(collected.values())
        messages.sort(
            key=lambda m: m.sent_at or datetime.min.replace(tzinfo=UTC), reverse=True
        )
        return messages[: query.limit]


def _within(sent_at: datetime | None, query: EmailQuery) -> bool:
    if sent_at is None:
        return True  # undated mail is rare; let the scorer judge it
    if query.after and sent_at < query.after:
        return False
    return not (query.before and sent_at > query.before)


def _addresses(entries: list[dict[str, Any]] | None) -> list[str]:
    result = []
    for entry in entries or []:
        address = ((entry or {}).get("emailAddress") or {}).get("address")
        if address:
            result.append(str(address).lower())
    return result


def _strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'")
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _parse_message(item: dict[str, Any]) -> FetchedMessage | None:
    if not item.get("id"):
        return None

    sender = ((item.get("from") or {}).get("emailAddress")) or {}
    body = item.get("body") or {}
    content = body.get("content") or ""
    if body.get("contentType") == "html":
        content = _strip_html(content)

    sent_at = None
    received = item.get("receivedDateTime")
    if received:
        try:
            parsed = datetime.fromisoformat(str(received).replace("Z", "+00:00"))
            sent_at = (
                parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            )
        except ValueError:  # pragma: no cover - malformed timestamp
            sent_at = None

    return FetchedMessage(
        provider_message_id=item["id"],
        thread_id=item.get("conversationId"),
        subject=item.get("subject"),
        from_address=(sender.get("address") or "").lower() or None,
        from_name=sender.get("name"),
        to_addresses=_addresses(item.get("toRecipients"))
        + _addresses(item.get("ccRecipients")),
        sent_at=sent_at,
        body=content or item.get("bodyPreview"),
    )
