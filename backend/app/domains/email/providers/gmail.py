"""Gmail adapter (Gmail API v1, read-only).

Reuses the same Google OAuth client as the calendar — the only difference is
the extra `gmail.readonly` scope, so connecting mail is one more consent
screen, not a second set of credentials.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta
from typing import Any

from app.core.config import settings
from app.core.errors import CalendarConnectionExpiredError, ProviderNotConfiguredError
from app.core.timeutils import UTC, utcnow
from app.domains.calendar.providers.http import request
from app.domains.email.providers.base import (
    EmailProviderAdapter,
    EmailQuery,
    FetchedMessage,
    extract_addresses,
)
from app.enums import ConnectionStatus, EmailProvider
from app.models import EmailAccount

logger = logging.getLogger(__name__)

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"

#: Read-only on purpose. The app never sends, deletes or modifies mail.
GMAIL_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
]


class GmailAdapter(EmailProviderAdapter):
    key = EmailProvider.GMAIL.value
    display_name = "Gmail"

    def is_configured(self, account: EmailAccount) -> bool:
        return bool(settings.google_configured and account.refresh_token)

    # -- tokens ------------------------------------------------------------

    def access_token(self, account: EmailAccount) -> str:
        """Return a usable access token, refreshing when close to expiry."""
        if not settings.google_configured:
            raise ProviderNotConfiguredError(
                "Gmail needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the "
                "backend .env file.",
                details={"missing": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]},
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
                f"The Gmail connection for {account.address} expired. "
                "Please reconnect the account.",
                code="email_connection_expired",
            )

        payload = request(
            "POST",
            TOKEN_URL,
            data={
                "refresh_token": account.refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token",
            },
            provider="gmail",
        )
        account.access_token = payload["access_token"]
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
            f"{GMAIL_API}/profile",
            access_token=self.access_token(account),
            provider="gmail",
        )
        return str(profile.get("emailAddress") or account.address)

    def search(self, account: EmailAccount, query: EmailQuery) -> list[FetchedMessage]:
        token = self.access_token(account)
        gmail_query = _build_query(query)
        if not gmail_query:
            return []

        listing = request(
            "GET",
            f"{GMAIL_API}/messages",
            access_token=token,
            params={"q": gmail_query, "maxResults": query.limit},
            provider="gmail",
        )
        ids = [item["id"] for item in listing.get("messages", []) if item.get("id")]

        messages: list[FetchedMessage] = []
        for message_id in ids[: query.limit]:
            payload = request(
                "GET",
                f"{GMAIL_API}/messages/{message_id}",
                access_token=token,
                params={"format": "full"},
                provider="gmail",
            )
            parsed = _parse_message(payload)
            if parsed is not None:
                messages.append(parsed)

        messages.sort(key=lambda m: m.sent_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        return messages


# --------------------------------------------------------------------------
# Query + payload mapping
# --------------------------------------------------------------------------


def _build_query(query: EmailQuery) -> str:
    """Translate the neutral query into Gmail search syntax.

    The people/domain clause is required — without it this would be an
    open-ended inbox scan, which is exactly what the design avoids.
    """
    who: list[str] = []
    who += [f"from:{address}" for address in query.participants]
    who += [f"to:{address}" for address in query.participants]
    who += [f"from:{domain}" for domain in query.domains]
    if not who:
        return ""

    parts = [f"({' OR '.join(who)})"]
    if query.after:
        parts.append(f"after:{query.after.strftime('%Y/%m/%d')}")
    if query.before:
        parts.append(f"before:{query.before.strftime('%Y/%m/%d')}")
    # Chat and calendar-invite noise add nothing the calendar does not already
    # have.
    parts.append("-in:chats")
    return " ".join(parts)


def _header(headers: list[dict[str, str]], name: str) -> str | None:
    lowered = name.lower()
    for header in headers:
        if header.get("name", "").lower() == lowered:
            return header.get("value")
    return None


def _decode(data: str | None) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except (ValueError, TypeError):  # pragma: no cover - malformed payload
        return ""


def _extract_body(payload: dict[str, Any]) -> str:
    """Walk the MIME tree for the best plain-text body available."""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})

    if mime == "text/plain" and body.get("data"):
        return _decode(body["data"])

    parts = payload.get("parts") or []
    # Prefer text/plain anywhere in the tree before falling back to HTML.
    for part in parts:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return _decode(part["body"]["data"])
    for part in parts:
        nested = _extract_body(part)
        if nested:
            return nested
    if mime == "text/html" and body.get("data"):
        return _strip_html(_decode(body["data"]))
    return ""


def _strip_html(html: str) -> str:
    import re

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'")
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _parse_message(payload: dict[str, Any]) -> FetchedMessage | None:
    if not payload.get("id"):
        return None
    headers = (payload.get("payload") or {}).get("headers", [])

    from_raw = _header(headers, "From")
    from_addresses = extract_addresses(from_raw)
    to_addresses = extract_addresses(
        " ".join(
            filter(None, [_header(headers, "To"), _header(headers, "Cc")])
        )
    )

    sent_at = None
    internal = payload.get("internalDate")
    if internal:
        try:
            sent_at = datetime.fromtimestamp(int(internal) / 1000, tz=UTC)
        except (ValueError, OSError):  # pragma: no cover - bad timestamp
            sent_at = None

    from_name = None
    if from_raw and "<" in from_raw:
        from_name = from_raw.split("<", 1)[0].strip().strip('"') or None

    return FetchedMessage(
        provider_message_id=payload["id"],
        thread_id=payload.get("threadId"),
        subject=_header(headers, "Subject"),
        from_address=from_addresses[0] if from_addresses else None,
        from_name=from_name,
        to_addresses=to_addresses,
        sent_at=sent_at,
        body=_extract_body(payload.get("payload") or {}) or payload.get("snippet"),
    )
