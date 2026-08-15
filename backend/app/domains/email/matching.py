"""Match email messages to a specific calendar event.

The anchor is always an event that already exists. This module turns that event
into a narrow query (who was involved, over what window) and then scores what
comes back, so only genuinely related mail reaches the model.

Pure functions where possible, so the scoring is testable without a mailbox.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.core.config import settings
from app.core.timeutils import overlaps  # noqa: F401  (kept for symmetry/tests)
from app.domains.calendar.detection import (
    ATS_DOMAINS,
    GENERIC_EMAIL_DOMAINS,
    STRONG_SIGNALS,
)
from app.domains.email.providers.base import EmailQuery, FetchedMessage, domain_of
from app.models import CalendarEvent, Person

#: Below this, a message is not considered related enough to send to the model.
MIN_MATCH_SCORE = 0.4


@dataclass
class ScoredMessage:
    message: FetchedMessage
    score: float
    reasons: list[str]


def counterparty_addresses(event: CalendarEvent, person: Person | None) -> list[str]:
    """Everyone on the event except the person themselves.

    Searching for the person's own address would match their entire mailbox;
    the useful signal is who they are talking *to*.
    """
    own = {a.lower() for a in [person.email] if person and person.email}
    own.update(
        a.lower()
        for a in [event.organizer_email]
        if a and person and person.email and a.lower() == person.email.lower()
    )

    addresses: list[str] = []
    if event.organizer_email:
        addresses.append(event.organizer_email.lower())
    for attendee in event.attendees or []:
        value = (attendee or {}).get("email")
        if value:
            addresses.append(str(value).lower())

    seen: set[str] = set()
    result = []
    for address in addresses:
        if address in own or address in seen:
            continue
        seen.add(address)
        result.append(address)
    return result


def company_domains(addresses: list[str]) -> list[str]:
    """Domains that plausibly identify an employer.

    Free-mail providers say nothing, and an ATS domain identifies the
    scheduling tool rather than the company.
    """
    domains: list[str] = []
    for address in addresses:
        domain = domain_of(address)
        if not domain:
            continue
        if domain in GENERIC_EMAIL_DOMAINS or domain.endswith(ATS_DOMAINS):
            continue
        if domain not in domains:
            domains.append(domain)
    return domains


def build_query(
    event: CalendarEvent,
    person: Person | None,
    *,
    lookback_days: int | None = None,
    lookahead_days: int | None = None,
    limit: int | None = None,
) -> EmailQuery:
    """Turn a calendar event into the narrowest useful mail query."""
    addresses = counterparty_addresses(event, person)
    domains = company_domains(addresses)

    lookback = lookback_days if lookback_days is not None else settings.email_lookback_days
    lookahead = (
        lookahead_days if lookahead_days is not None else settings.email_lookahead_days
    )

    terms = []
    if event.title:
        terms.append(event.title)

    return EmailQuery(
        participants=addresses,
        domains=domains,
        after=event.starts_at - timedelta(days=lookback),
        before=event.starts_at + timedelta(days=lookahead),
        terms=terms,
        limit=limit or max(settings.email_max_messages_per_event * 3, 10),
    )


def score_message(
    message: FetchedMessage,
    event: CalendarEvent,
    participants: list[str],
    domains: list[str],
) -> ScoredMessage:
    """How strongly this message relates to this event."""
    score = 0.0
    reasons: list[str] = []

    participant_set = {a.lower() for a in participants}
    message_participants = set(message.participants)
    shared = participant_set & message_participants
    if shared:
        score += 0.5
        reasons.append(f"Involves {sorted(shared)[0]}")

    from_domain = domain_of(message.from_address)
    if from_domain and from_domain in domains:
        score += 0.3
        reasons.append(f"From the {from_domain} domain")

    haystack = f"{message.subject or ''} {message.body or ''}".lower()
    for phrase in ("interview", "schedule", "onsite", "recruiter", "next round", "offer"):
        if phrase in haystack:
            score += 0.15
            reasons.append(f'Mentions "{phrase}"')
            break

    for phrase in STRONG_SIGNALS:
        if phrase in (message.subject or "").lower():
            score += 0.1
            break

    # Mail written close to the event is far more likely to be about it.
    if message.sent_at is not None:
        days = abs((event.starts_at - message.sent_at).days)
        if days <= 3:
            score += 0.2
            reasons.append("Sent within days of the interview")
        elif days <= 14:
            score += 0.1

    return ScoredMessage(message=message, score=round(min(score, 1.0), 3), reasons=reasons[:4])


def select_messages(
    messages: list[FetchedMessage],
    event: CalendarEvent,
    participants: list[str],
    domains: list[str],
    *,
    limit: int | None = None,
    min_score: float = MIN_MATCH_SCORE,
) -> list[ScoredMessage]:
    """Score, filter and cap the messages that will be sent to the model."""
    scored = [score_message(m, event, participants, domains) for m in messages]
    kept = [s for s in scored if s.score >= min_score]
    # Best match first, then most recent — the newest mail usually states the
    # current round most clearly.
    kept.sort(
        key=lambda s: (s.score, s.message.sent_at.timestamp() if s.message.sent_at else 0),
        reverse=True,
    )
    return kept[: limit or settings.email_max_messages_per_event]
