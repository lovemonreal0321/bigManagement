"""Email provider adapters: payload mapping and query construction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domains.email.providers import get_email_adapter
from app.domains.email.providers.base import EmailQuery, domain_of, extract_addresses
from app.domains.email.providers.imap import suggest_host
from app.domains.email.providers.microsoft import _parse_message, _within

BASE = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)


class TestRegistry:
    def test_all_three_providers_resolve(self) -> None:
        assert get_email_adapter("gmail").display_name == "Gmail"
        assert get_email_adapter("microsoft").display_name == "Outlook"
        assert "IMAP" in get_email_adapter("imap").display_name

    def test_unknown_provider_is_rejected(self) -> None:
        from app.core.errors import ValidationError

        with pytest.raises(ValidationError):
            get_email_adapter("pigeon")


class TestOutlookMapping:
    def _payload(self, **overrides):
        base = {
            "id": "AAMkAG=",
            "conversationId": "thread-1",
            "subject": "Second round — technical",
            "from": {"emailAddress": {"name": "Ana", "address": "Ana@Contoso.com"}},
            "toRecipients": [{"emailAddress": {"address": "john@example.com"}}],
            "ccRecipients": [{"emailAddress": {"address": "hr@contoso.com"}}],
            "receivedDateTime": "2026-08-19T09:30:00Z",
            "body": {"contentType": "text", "content": "You're through to round two."},
        }
        base.update(overrides)
        return base

    def test_maps_the_fields_we_use(self) -> None:
        message = _parse_message(self._payload())
        assert message is not None
        assert message.provider_message_id == "AAMkAG="
        assert message.thread_id == "thread-1"
        assert message.subject == "Second round — technical"
        assert message.from_name == "Ana"
        assert message.sent_at == datetime(2026, 8, 19, 9, 30, tzinfo=UTC)
        assert "round two" in (message.body or "")

    def test_addresses_are_lowercased(self) -> None:
        """Matching compares addresses, so case must not create a mismatch."""
        message = _parse_message(self._payload())
        assert message is not None
        assert message.from_address == "ana@contoso.com"
        assert "john@example.com" in message.to_addresses

    def test_cc_recipients_count_as_participants(self) -> None:
        message = _parse_message(self._payload())
        assert message is not None
        assert "hr@contoso.com" in message.participants

    def test_html_bodies_are_flattened(self) -> None:
        message = _parse_message(
            self._payload(
                body={
                    "contentType": "html",
                    "content": "<p>Hi <b>John</b></p><script>x()</script><p>Round 2</p>",
                }
            )
        )
        assert message is not None
        assert "<p>" not in (message.body or "")
        assert "x()" not in (message.body or ""), "script contents must be dropped"
        assert "Round 2" in (message.body or "")

    def test_message_without_an_id_is_skipped(self) -> None:
        assert _parse_message({"subject": "no id"}) is None

    def test_unreadable_timestamp_does_not_lose_the_message(self) -> None:
        message = _parse_message(self._payload(receivedDateTime="not-a-date"))
        assert message is not None
        assert message.sent_at is None


class TestOutlookWindowing:
    """`$search` cannot be combined with `$filter`, so the window is applied
    client-side; that logic needs to be right."""

    def _query(self) -> EmailQuery:
        return EmailQuery(
            participants=["ana@contoso.com"],
            after=BASE - timedelta(days=30),
            before=BASE + timedelta(days=7),
        )

    def test_inside_the_window(self) -> None:
        assert _within(BASE - timedelta(days=2), self._query())

    def test_too_old(self) -> None:
        assert not _within(BASE - timedelta(days=200), self._query())

    def test_too_new(self) -> None:
        assert not _within(BASE + timedelta(days=60), self._query())

    def test_undated_mail_is_kept_for_the_scorer_to_judge(self) -> None:
        assert _within(None, self._query())


class TestAddressHelpers:
    def test_extracts_from_a_display_name_header(self) -> None:
        assert extract_addresses('"Ana R" <ana@contoso.com>') == ["ana@contoso.com"]

    def test_extracts_several(self) -> None:
        found = extract_addresses("a@x.com, B@Y.com")
        assert found == ["a@x.com", "b@y.com"]

    def test_domain_of(self) -> None:
        assert domain_of("ana@Contoso.com") == "contoso.com"
        assert domain_of("nonsense") is None


class TestImapHostPresets:
    @pytest.mark.parametrize(
        ("address", "host"),
        [
            ("me@yahoo.com", "imap.mail.yahoo.com"),
            ("me@ymail.com", "imap.mail.yahoo.com"),
            ("me@icloud.com", "imap.mail.me.com"),
            ("me@outlook.com", "outlook.office365.com"),
        ],
    )
    def test_known_providers_prefill(self, address: str, host: str) -> None:
        assert suggest_host(address)[0] == host

    def test_unknown_provider_needs_a_manual_host(self) -> None:
        host, port, folders = suggest_host("me@acme.dev")
        assert host is None
        assert port == 993
        assert folders == ["INBOX"]
