"""Generic IMAP adapter — the route Yahoo still supports.

Yahoo closed its OAuth/API partner programme to new third-party apps, so an
app-specific password over IMAP is the only workable option there. The same
adapter covers iCloud, Fastmail, Outlook and Gmail, so "add another mailbox"
never needs new code.

Passwords are stored encrypted (`core/crypto.py`) and only decrypted for the
duration of a connection.
"""

from __future__ import annotations

import contextlib
import email
import imaplib
import logging
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime

from app.core.crypto import DecryptionError, decrypt
from app.core.errors import AppError, ValidationError
from app.core.timeutils import UTC
from app.domains.email.providers.base import (
    EmailProviderAdapter,
    EmailQuery,
    FetchedMessage,
    extract_addresses,
)
from app.enums import EmailProvider
from app.models import EmailAccount

logger = logging.getLogger(__name__)

DEFAULT_FOLDERS = ["INBOX"]
CONNECT_TIMEOUT = 20

#: Host presets so the user only has to type an address and app password.
KNOWN_HOSTS: dict[str, tuple[str, int, list[str]]] = {
    "yahoo.com": ("imap.mail.yahoo.com", 993, ["INBOX", "Archive"]),
    "yahoo.co.uk": ("imap.mail.yahoo.com", 993, ["INBOX", "Archive"]),
    "ymail.com": ("imap.mail.yahoo.com", 993, ["INBOX", "Archive"]),
    "rocketmail.com": ("imap.mail.yahoo.com", 993, ["INBOX", "Archive"]),
    "aol.com": ("imap.aol.com", 993, ["INBOX", "Archive"]),
    "gmail.com": ("imap.gmail.com", 993, ["INBOX", "[Gmail]/All Mail"]),
    "googlemail.com": ("imap.gmail.com", 993, ["INBOX", "[Gmail]/All Mail"]),
    "outlook.com": ("outlook.office365.com", 993, ["INBOX", "Archive"]),
    "hotmail.com": ("outlook.office365.com", 993, ["INBOX", "Archive"]),
    "live.com": ("outlook.office365.com", 993, ["INBOX", "Archive"]),
    "icloud.com": ("imap.mail.me.com", 993, ["INBOX", "Archive"]),
    "me.com": ("imap.mail.me.com", 993, ["INBOX", "Archive"]),
    "fastmail.com": ("imap.fastmail.com", 993, ["INBOX", "Archive"]),
}


def suggest_host(address: str) -> tuple[str | None, int, list[str]]:
    """Best-guess IMAP settings from an address, so the form can prefill."""
    domain = address.rsplit("@", 1)[-1].strip().lower() if "@" in address else ""
    if domain in KNOWN_HOSTS:
        host, port, folders = KNOWN_HOSTS[domain]
        return host, port, folders
    return None, 993, list(DEFAULT_FOLDERS)


class ImapError(AppError):
    status_code = 502
    code = "imap_error"
    message = "Could not reach the mail server."


class ImapAdapter(EmailProviderAdapter):
    key = EmailProvider.IMAP.value
    display_name = "IMAP (Yahoo, iCloud, Outlook…)"

    def is_configured(self, account: EmailAccount) -> bool:
        return bool(
            account.imap_host and account.imap_username and account.imap_password_encrypted
        )

    # -- connection --------------------------------------------------------

    def _connect(self, account: EmailAccount) -> imaplib.IMAP4:
        if not self.is_configured(account):
            raise ValidationError(
                "This mailbox is missing its server settings. Edit the account "
                "and add the host, username and app password.",
                code="imap_not_configured",
            )
        try:
            password = decrypt(account.imap_password_encrypted or "")
        except DecryptionError as exc:
            raise ValidationError(str(exc), code="imap_credentials_unreadable") from exc

        host = account.imap_host or ""
        port = account.imap_port or 993
        try:
            client: imaplib.IMAP4 = (
                imaplib.IMAP4_SSL(host, port, timeout=CONNECT_TIMEOUT)
                if account.imap_use_ssl
                else imaplib.IMAP4(host, port, timeout=CONNECT_TIMEOUT)
            )
        except (OSError, imaplib.IMAP4.error) as exc:
            raise ImapError(
                f"Could not connect to {host}:{port}. Check the server address.",
                retryable=True,
            ) from exc

        try:
            client.login(account.imap_username or "", password)
        except imaplib.IMAP4.error as exc:
            # Yahoo and Gmail both reject the normal account password here, and
            # the message is otherwise cryptic.
            raise ValidationError(
                "The mail server rejected those credentials. Most providers "
                "require an app-specific password rather than your normal one.",
                code="imap_auth_failed",
            ) from exc
        return client

    def verify(self, account: EmailAccount) -> str:
        client = self._connect(account)
        try:
            status, _ = client.select("INBOX", readonly=True)
            if status != "OK":
                raise ImapError("Connected, but the INBOX could not be opened.")
        finally:
            _safe_logout(client)
        return account.address

    # -- search ------------------------------------------------------------

    def search(self, account: EmailAccount, query: EmailQuery) -> list[FetchedMessage]:
        if not query.participants and not query.domains:
            return []

        folders = account.imap_folders or DEFAULT_FOLDERS
        client = self._connect(account)
        collected: dict[str, FetchedMessage] = {}

        try:
            for folder in folders:
                try:
                    status, _ = client.select(_quote_folder(folder), readonly=True)
                    if status != "OK":
                        continue
                except imaplib.IMAP4.error:
                    continue  # folder does not exist on this provider

                for uid in self._search_folder(client, query):
                    if uid in collected:
                        continue
                    message = self._fetch(client, uid)
                    if message is not None:
                        collected[uid] = message
                    if len(collected) >= query.limit:
                        break
                if len(collected) >= query.limit:
                    break
        finally:
            _safe_logout(client)

        messages = list(collected.values())
        messages.sort(
            key=lambda m: m.sent_at or datetime.min.replace(tzinfo=UTC), reverse=True
        )
        return messages[: query.limit]

    def _search_folder(self, client: imaplib.IMAP4, query: EmailQuery) -> list[str]:
        """Run one SEARCH per participant and union the results.

        IMAP's OR is prefix-notation and awkward to nest reliably across
        servers, so several small searches beat one clever query.
        """
        since = None
        if query.after:
            since = query.after.strftime("%d-%b-%Y")
        before = None
        if query.before:
            # IMAP BEFORE is exclusive; pad by a day so the window is inclusive.
            before = (query.before + timedelta(days=1)).strftime("%d-%b-%Y")

        needles = [("FROM", value) for value in query.participants]
        needles += [("TO", value) for value in query.participants]
        needles += [("FROM", value) for value in query.domains]

        uids: list[str] = []
        seen: set[str] = set()
        for key, value in needles:
            criteria: list[str] = []
            if since:
                criteria += ["SINCE", since]
            if before:
                criteria += ["BEFORE", before]
            criteria += [key, f'"{value}"']
            try:
                status, data = client.uid("SEARCH", None, *criteria)  # type: ignore[arg-type]
            except imaplib.IMAP4.error:
                continue
            if status != "OK" or not data or not data[0]:
                continue
            for raw in data[0].split():
                uid = raw.decode()
                if uid not in seen:
                    seen.add(uid)
                    uids.append(uid)
            if len(uids) >= query.limit * 2:
                break
        # Highest UID is the most recent message.
        return sorted(uids, key=lambda value: int(value) if value.isdigit() else 0, reverse=True)

    def _fetch(self, client: imaplib.IMAP4, uid: str) -> FetchedMessage | None:
        try:
            status, data = client.uid("FETCH", uid, "(RFC822)")
        except imaplib.IMAP4.error:
            return None
        if status != "OK" or not data or not isinstance(data[0], tuple):
            return None

        try:
            parsed = email.message_from_bytes(data[0][1])
        except Exception:  # pragma: no cover - malformed message
            return None
        return _to_fetched(parsed, uid)


# --------------------------------------------------------------------------
# Message parsing
# --------------------------------------------------------------------------


def _decode_header(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # pragma: no cover - exotic encodings
        return value


def _body_text(message: Message) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                return _payload_text(part)
        for part in message.walk():
            if part.get_content_type() == "text/html":
                return _strip_html(_payload_text(part))
        return ""
    if message.get_content_type() == "text/html":
        return _strip_html(_payload_text(message))
    return _payload_text(message)


def _payload_text(part: Message) -> str:
    try:
        payload = part.get_payload(decode=True)
    except Exception:  # pragma: no cover
        return ""
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


def _strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'")
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _to_fetched(message: Message, uid: str) -> FetchedMessage:
    from_raw = message.get("From")
    from_addresses = extract_addresses(from_raw)
    to_addresses = extract_addresses(
        " ".join(filter(None, [message.get("To"), message.get("Cc")]))
    )

    sent_at = None
    if message.get("Date"):
        try:
            parsed = parsedate_to_datetime(message["Date"])
            sent_at = parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except (TypeError, ValueError):  # pragma: no cover - bad Date header
            sent_at = None

    from_name = None
    decoded_from = _decode_header(from_raw)
    if decoded_from and "<" in decoded_from:
        from_name = decoded_from.split("<", 1)[0].strip().strip('"') or None

    return FetchedMessage(
        # Message-ID is stable across sessions; UID is not guaranteed to be.
        provider_message_id=(message.get("Message-ID") or f"uid-{uid}").strip("<> "),
        thread_id=(message.get("References") or "").split()[0].strip("<> ") or None
        if message.get("References")
        else None,
        subject=_decode_header(message.get("Subject")),
        from_address=from_addresses[0] if from_addresses else None,
        from_name=from_name,
        to_addresses=to_addresses,
        sent_at=sent_at,
        body=_body_text(message),
    )


def _quote_folder(folder: str) -> str:
    return f'"{folder}"' if " " in folder or "/" in folder else folder


def _safe_logout(client: imaplib.IMAP4) -> None:
    # Best-effort cleanup: a mailbox that is already closed, or a server that
    # dropped the connection, must not surface as an error to the user.
    with contextlib.suppress(Exception):
        client.close()
    with contextlib.suppress(Exception):
        client.logout()
