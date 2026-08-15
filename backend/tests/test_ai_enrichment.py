"""Calendar-triggered AI enrichment.

The model is stubbed throughout — these test the pipeline around it: what gets
matched, what gets written, and that undo removes exactly what was created and
nothing else.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.domains.ai import enrichment, kimi
from app.domains.ai.extraction import parse_result
from app.domains.ai.kimi import AiResponse, parse_json_object
from app.domains.email import matching
from app.domains.email.providers.base import EmailQuery, FetchedMessage
from app.enums import ExtractionStatus
from app.models import (
    Application,
    CalendarEvent,
    EmailMessage,
    InterviewEvent,
    InterviewStage,
    Person,
    Workspace,
)

EVENT_START = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)


@pytest.fixture
def john(make_person) -> Person:
    person = make_person("John Carter")
    person.email = "john@example.com"
    return person


@pytest.fixture
def event(db: Session, john: Person) -> CalendarEvent:
    row = CalendarEvent(
        person_id=john.id,
        provider="google",
        provider_event_id="evt-1",
        title="Amazon — Technical Interview",
        description="Second round with the team.",
        organizer_email="recruiter@amazon.com",
        organizer_name="Ana Recruiter",
        attendees=[
            {"email": "recruiter@amazon.com"},
            {"email": "john@example.com"},
            {"email": "engineer@amazon.com"},
        ],
        starts_at=EVENT_START,
        ends_at=EVENT_START + timedelta(hours=1),
        detection_score=0.9,
    )
    db.add(row)
    db.commit()
    return row


def _stub_model(monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    import json

    monkeypatch.setattr(kimi, "is_configured", lambda: True)
    monkeypatch.setattr(enrichment.kimi, "is_configured", lambda: True)
    monkeypatch.setattr(
        enrichment.kimi,
        "complete",
        lambda **kwargs: AiResponse(
            content=json.dumps(payload), model="kimi-test", tokens_used=321
        ),
    )


def _no_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(enrichment, "gather_messages", lambda db, event, person: [])


GOOD_RESULT = {
    "is_interview": True,
    "company": "Amazon",
    "role": "Senior AI Engineer",
    "round_number": 2,
    "interview_type": "technical",
    "stage_name": "Technical Interview",
    "interviewers": ["Ana Recruiter"],
    "next_steps": "Result expected within a week.",
    "confidence": 0.92,
    "reasoning": "The thread says 'second round technical'.",
}


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------


class TestMatching:
    def test_query_excludes_the_person_themselves(
        self, event: CalendarEvent, john: Person
    ) -> None:
        """Searching for the candidate's own address would match everything."""
        query = matching.build_query(event, john)
        assert "john@example.com" not in query.participants
        assert "recruiter@amazon.com" in query.participants
        assert "engineer@amazon.com" in query.participants

    def test_company_domain_is_derived(self, event: CalendarEvent, john: Person) -> None:
        query = matching.build_query(event, john)
        assert "amazon.com" in query.domains

    def test_free_mail_and_ats_domains_are_not_companies(self) -> None:
        domains = matching.company_domains(
            ["a@gmail.com", "b@greenhouse.io", "c@stripe.com"]
        )
        assert domains == ["stripe.com"]

    def test_window_brackets_the_event(self, event: CalendarEvent, john: Person) -> None:
        query = matching.build_query(event, john, lookback_days=30, lookahead_days=5)
        assert query.after == EVENT_START - timedelta(days=30)
        assert query.before == EVENT_START + timedelta(days=5)

    def test_message_from_a_participant_scores_highly(
        self, event: CalendarEvent, john: Person
    ) -> None:
        query = matching.build_query(event, john)
        message = FetchedMessage(
            provider_message_id="m1",
            subject="Your second round interview",
            from_address="recruiter@amazon.com",
            to_addresses=["john@example.com"],
            sent_at=EVENT_START - timedelta(days=1),
            body="Confirming your technical interview.",
        )
        scored = matching.score_message(message, event, query.participants, query.domains)
        assert scored.score >= matching.MIN_MATCH_SCORE
        assert scored.reasons

    def test_unrelated_message_is_filtered_out(
        self, event: CalendarEvent, john: Person
    ) -> None:
        query = matching.build_query(event, john)
        message = FetchedMessage(
            provider_message_id="m2",
            subject="Your parcel has shipped",
            from_address="noreply@parcels.example",
            sent_at=EVENT_START - timedelta(days=200),
            body="Tracking number 123",
        )
        kept = matching.select_messages(
            [message], event, query.participants, query.domains
        )
        assert kept == []

    def test_selection_is_capped(self, event: CalendarEvent, john: Person) -> None:
        query = matching.build_query(event, john)
        messages = [
            FetchedMessage(
                provider_message_id=f"m{i}",
                subject="Interview scheduling",
                from_address="recruiter@amazon.com",
                sent_at=EVENT_START - timedelta(days=i),
                body="interview",
            )
            for i in range(30)
        ]
        kept = matching.select_messages(
            messages, event, query.participants, query.domains, limit=4
        )
        assert len(kept) == 4


# --------------------------------------------------------------------------
# Model response handling
# --------------------------------------------------------------------------


class TestResponseParsing:
    def test_plain_json(self) -> None:
        assert parse_json_object('{"a": 1}') == {"a": 1}

    def test_fenced_json(self) -> None:
        assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}

    def test_json_after_prose(self) -> None:
        assert parse_json_object('Sure! Here you go:\n{"a": 1}\nHope that helps.') == {
            "a": 1
        }

    def test_unparseable_raises(self) -> None:
        from app.domains.ai.kimi import AiError

        with pytest.raises(AiError):
            parse_json_object("no json at all")

    def test_percent_confidence_is_normalised(self) -> None:
        assert parse_result({"confidence": 85}).confidence == 0.85

    def test_round_number_as_string(self) -> None:
        assert parse_result({"round_number": "3"}).round_number == 3

    def test_nullish_strings_become_none(self) -> None:
        result = parse_result({"company": "unknown", "role": "N/A"})
        assert result.company is None
        assert result.role is None


# --------------------------------------------------------------------------
# Enrichment
# --------------------------------------------------------------------------


class TestEnrichment:
    def test_creates_application_and_stage(
        self, db, workspace: Workspace, event: CalendarEvent, monkeypatch
    ) -> None:
        _no_email(monkeypatch)
        _stub_model(monkeypatch, GOOD_RESULT)

        extraction = enrichment.enrich_event(db, workspace, event)

        assert extraction.status == ExtractionStatus.APPLIED.value
        assert extraction.tokens_used == 321

        application = db.get(Application, extraction.created_application_id)
        assert application is not None
        assert application.company_name == "Amazon"
        assert application.job_title == "Senior AI Engineer"

        stage = db.get(InterviewStage, extraction.created_stage_id)
        assert stage is not None
        assert stage.round_number == 2
        assert stage.type_key == "technical"
        assert stage.status == "scheduled"

        # The calendar event backs the interview and is now locked.
        db.refresh(event)
        assert event.classification == "interview"
        assert event.classification_locked is True
        link = db.query(InterviewEvent).filter_by(interview_stage_id=stage.id).one()
        assert link.calendar_event_id == event.id
        # It came from the provider, so write-back must never touch it.
        assert link.source == "external_provider"

    def test_reuses_an_existing_application(
        self, db, workspace: Workspace, event: CalendarEvent, john: Person, monkeypatch
    ) -> None:
        """A second round must not create a second Amazon application."""
        from app.domains.applications.service import create_application
        from app.schemas.application import ApplicationCreate

        existing = create_application(
            db,
            workspace,
            ApplicationCreate(
                person_id=john.id, company_name="Amazon", job_title="Senior AI Engineer"
            ),
        )
        _no_email(monkeypatch)
        _stub_model(monkeypatch, GOOD_RESULT)

        extraction = enrichment.enrich_event(db, workspace, event)

        assert extraction.linked_existing_application is True
        assert extraction.created_application_id is None
        stage = db.get(InterviewStage, extraction.created_stage_id)
        assert stage.application_id == existing.id
        assert db.query(Application).count() == 1

    def test_company_matching_tolerates_suffixes(
        self, db, workspace: Workspace, event: CalendarEvent, john: Person, monkeypatch
    ) -> None:
        from app.domains.applications.service import create_application
        from app.schemas.application import ApplicationCreate

        create_application(
            db,
            workspace,
            ApplicationCreate(
                person_id=john.id, company_name="Amazon Inc.", job_title="Engineer"
            ),
        )
        _no_email(monkeypatch)
        _stub_model(monkeypatch, GOOD_RESULT)

        enrichment.enrich_event(db, workspace, event)
        assert db.query(Application).count() == 1

    def test_low_confidence_only_suggests(
        self, db, workspace: Workspace, event: CalendarEvent, monkeypatch
    ) -> None:
        _no_email(monkeypatch)
        _stub_model(monkeypatch, {**GOOD_RESULT, "confidence": 0.4})

        extraction = enrichment.enrich_event(db, workspace, event)

        assert extraction.status == ExtractionStatus.SUGGESTED.value
        assert extraction.created_application_id is None
        assert db.query(Application).count() == 0

    def test_a_suggestion_can_be_accepted_later(
        self, db, workspace: Workspace, event: CalendarEvent, monkeypatch
    ) -> None:
        _no_email(monkeypatch)
        _stub_model(monkeypatch, {**GOOD_RESULT, "confidence": 0.4})
        extraction = enrichment.enrich_event(db, workspace, event)

        applied = enrichment.apply_suggestion(db, workspace, extraction.id)

        assert applied.status == ExtractionStatus.APPLIED.value
        assert db.query(Application).count() == 1

    def test_non_interview_creates_nothing(
        self, db, workspace: Workspace, event: CalendarEvent, monkeypatch
    ) -> None:
        _no_email(monkeypatch)
        _stub_model(monkeypatch, {"is_interview": False, "confidence": 0.9})

        extraction = enrichment.enrich_event(db, workspace, event)

        assert extraction.status == ExtractionStatus.NO_MATCHES.value
        assert db.query(Application).count() == 0

    def test_missing_company_is_not_actionable(
        self, db, workspace: Workspace, event: CalendarEvent, monkeypatch
    ) -> None:
        _no_email(monkeypatch)
        _stub_model(
            monkeypatch, {"is_interview": True, "company": None, "confidence": 0.99}
        )

        extraction = enrichment.enrich_event(db, workspace, event)

        assert extraction.status == ExtractionStatus.SUGGESTED.value
        assert db.query(Application).count() == 0

    def test_round_falls_back_to_sequence_when_unknown(
        self, db, workspace: Workspace, event: CalendarEvent, monkeypatch
    ) -> None:
        """The model must not invent a round, but the record still needs one."""
        _no_email(monkeypatch)
        _stub_model(monkeypatch, {**GOOD_RESULT, "round_number": None})

        extraction = enrichment.enrich_event(db, workspace, event)
        stage = db.get(InterviewStage, extraction.created_stage_id)
        assert stage.round_number == 1

    def test_is_idempotent_per_event(
        self, db, workspace: Workspace, event: CalendarEvent, monkeypatch
    ) -> None:
        _no_email(monkeypatch)
        _stub_model(monkeypatch, GOOD_RESULT)

        first = enrichment.enrich_event(db, workspace, event)
        second = enrichment.enrich_event(db, workspace, event)

        assert first.id == second.id
        assert db.query(Application).count() == 1
        assert db.query(InterviewStage).count() == 1

    def test_model_failure_is_recorded_not_raised(
        self, db, workspace: Workspace, event: CalendarEvent, monkeypatch
    ) -> None:
        from app.domains.ai.kimi import AiError

        _no_email(monkeypatch)
        monkeypatch.setattr(enrichment.kimi, "is_configured", lambda: True)

        def boom(**kwargs):
            raise AiError("Provider exploded")

        monkeypatch.setattr(enrichment.kimi, "complete", boom)

        extraction = enrichment.enrich_event(db, workspace, event)

        assert extraction.status == ExtractionStatus.FAILED.value
        assert "exploded" in (extraction.error or "")

    def test_without_a_key_it_says_so(
        self, db, workspace: Workspace, event: CalendarEvent, monkeypatch
    ) -> None:
        _no_email(monkeypatch)
        monkeypatch.setattr(enrichment.kimi, "is_configured", lambda: False)

        extraction = enrichment.enrich_event(db, workspace, event)

        assert extraction.status == ExtractionStatus.FAILED.value
        assert "KIMI_API_KEY" in (extraction.error or "")


# --------------------------------------------------------------------------
# Undo
# --------------------------------------------------------------------------


class TestUndo:
    def test_removes_what_it_created(
        self, db, workspace: Workspace, event: CalendarEvent, monkeypatch
    ) -> None:
        _no_email(monkeypatch)
        _stub_model(monkeypatch, GOOD_RESULT)
        extraction = enrichment.enrich_event(db, workspace, event)
        assert db.query(Application).count() == 1

        enrichment.undo(db, workspace, extraction.id)

        assert db.query(Application).count() == 0
        assert db.query(InterviewStage).count() == 0
        assert db.query(InterviewEvent).count() == 0

        db.refresh(extraction)
        assert extraction.status == ExtractionStatus.UNDONE.value
        assert extraction.undone_at is not None

    def test_keeps_an_application_it_did_not_create(
        self, db, workspace: Workspace, event: CalendarEvent, john: Person, monkeypatch
    ) -> None:
        """Undo must remove the added round, not the user's own application."""
        from app.domains.applications.service import create_application
        from app.schemas.application import ApplicationCreate

        existing = create_application(
            db,
            workspace,
            ApplicationCreate(
                person_id=john.id, company_name="Amazon", job_title="Senior AI Engineer"
            ),
        )
        _no_email(monkeypatch)
        _stub_model(monkeypatch, GOOD_RESULT)
        extraction = enrichment.enrich_event(db, workspace, event)

        enrichment.undo(db, workspace, extraction.id)

        assert db.get(Application, existing.id) is not None
        assert db.query(InterviewStage).count() == 0

    def test_returns_the_event_to_manual_triage(
        self, db, workspace: Workspace, event: CalendarEvent, monkeypatch
    ) -> None:
        _no_email(monkeypatch)
        _stub_model(monkeypatch, GOOD_RESULT)
        extraction = enrichment.enrich_event(db, workspace, event)

        enrichment.undo(db, workspace, extraction.id)

        db.refresh(event)
        assert event.classification == "unclassified"
        assert event.classification_locked is False
        # And it should not immediately be re-suggested.
        assert event.detection_dismissed is True

    def test_is_idempotent(
        self, db, workspace: Workspace, event: CalendarEvent, monkeypatch
    ) -> None:
        _no_email(monkeypatch)
        _stub_model(monkeypatch, GOOD_RESULT)
        extraction = enrichment.enrich_event(db, workspace, event)

        enrichment.undo(db, workspace, extraction.id)
        enrichment.undo(db, workspace, extraction.id)

        assert db.query(Application).count() == 0


# --------------------------------------------------------------------------
# Email gathering
# --------------------------------------------------------------------------


def test_messages_are_stored_with_their_match_reasons(
    db, workspace: Workspace, event: CalendarEvent, john: Person, monkeypatch
) -> None:
    """Provenance: the UI shows which emails were read and why."""
    from app.core.crypto import encrypt
    from app.enums import EmailProvider
    from app.models import EmailAccount

    account = EmailAccount(
        person_id=john.id,
        provider=EmailProvider.IMAP.value,
        address="john@example.com",
        imap_host="imap.example.com",
        imap_username="john@example.com",
        imap_password_encrypted=encrypt("app-password"),
    )
    db.add(account)
    db.commit()

    class FakeAdapter:
        def search(self, account, query: EmailQuery):
            assert "recruiter@amazon.com" in query.participants
            return [
                FetchedMessage(
                    provider_message_id="msg-1",
                    subject="Second round interview",
                    from_address="recruiter@amazon.com",
                    to_addresses=["john@example.com"],
                    sent_at=EVENT_START - timedelta(days=2),
                    body="You're through to the second round technical interview.",
                )
            ]

    monkeypatch.setattr(
        enrichment, "get_email_adapter", lambda provider: FakeAdapter()
    )

    stored = enrichment.gather_messages(db, event, john)

    assert len(stored) == 1
    assert stored[0].subject == "Second round interview"
    assert stored[0].match_score >= matching.MIN_MATCH_SCORE
    assert stored[0].match_reasons
    assert db.query(EmailMessage).count() == 1


def test_no_counterparty_means_no_search(
    db, workspace: Workspace, john: Person, monkeypatch
) -> None:
    """An event with only the candidate on it must not trigger a mailbox scan."""
    solo = CalendarEvent(
        person_id=john.id,
        title="Focus time",
        starts_at=EVENT_START,
        ends_at=EVENT_START + timedelta(hours=1),
        attendees=[{"email": "john@example.com"}],
    )
    db.add(solo)
    db.commit()

    called = False

    class ExplodingAdapter:
        def search(self, account, query):
            nonlocal called
            called = True
            return []

    monkeypatch.setattr(
        enrichment, "get_email_adapter", lambda provider: ExplodingAdapter()
    )
    assert enrichment.gather_messages(db, solo, john) == []
    assert called is False
