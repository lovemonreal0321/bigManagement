"""Integration tests over the HTTP API (spec §57: core CRUD workflows)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

API = "/api/v1"

#: People are seeded in this zone by the `make_person` fixture, and the backend
#: dates things in the *person's* timezone — not the machine's. Tests must use
#: the same clock, or they pass or fail depending on the hour they run at.
PERSON_TZ = ZoneInfo("America/New_York")


def person_today() -> date:
    return datetime.now(PERSON_TZ).date()


def _person(client: TestClient, headers: dict[str, str], name: str = "John Carter") -> dict:
    response = client.post(f"{API}/people", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _application(
    client: TestClient,
    headers: dict[str, str],
    person_id: str,
    company: str = "Amazon",
    **extra,
) -> dict:
    payload = {
        "person_id": person_id,
        "company_name": company,
        "job_title": "Senior AI Engineer",
        **extra,
    }
    response = client.post(f"{API}/applications", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestAuth:
    def test_login_succeeds_with_the_configured_credentials(
        self, client: TestClient
    ) -> None:
        response = client.post(
            f"{API}/auth/login", json={"username": "admin321", "password": "admin321"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["user"]["username"] == "admin321"

    def test_wrong_password_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            f"{API}/auth/login", json={"username": "admin321", "password": "nope"}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"

    def test_error_message_is_friendly_not_raw(self, client: TestClient) -> None:
        """Spec §58: never leak internals to the user."""
        response = client.post(
            f"{API}/auth/login", json={"username": "ghost", "password": "x"}
        )
        assert "Traceback" not in response.text
        assert response.json()["error"]["message"] == "Incorrect username or password."

    def test_protected_routes_require_a_token(self, client: TestClient) -> None:
        assert client.get(f"{API}/people").status_code == 401

    def test_a_bogus_token_is_rejected(self, client: TestClient) -> None:
        response = client.get(
            f"{API}/people", headers={"Authorization": "Bearer not-a-token"}
        )
        assert response.status_code == 401

    def test_me_returns_the_current_user(self, client: TestClient, auth_headers) -> None:
        response = client.get(f"{API}/auth/me", headers=auth_headers)
        assert response.json()["username"] == "admin321"


class TestPeopleCrud:
    def test_create_assigns_initials_colour_and_timezone(
        self, client: TestClient, auth_headers
    ) -> None:
        person = _person(client, auth_headers, "John Carter")
        assert person["initials"] == "JC"
        assert person["color"].startswith("#")
        assert person["timezone"]

    def test_each_person_gets_a_distinct_colour(
        self, client: TestClient, auth_headers
    ) -> None:
        """Spec §5: colour identity must be unique and consistent."""
        colours = {
            _person(client, auth_headers, name)["color"]
            for name in ("John Carter", "David Okafor", "Sarah Lindqvist")
        }
        assert len(colours) == 3

    def test_duplicate_names_are_rejected(
        self, client: TestClient, auth_headers
    ) -> None:
        _person(client, auth_headers, "John Carter")
        response = client.post(
            f"{API}/people", json={"name": "John Carter"}, headers=auth_headers
        )
        assert response.status_code == 409

    def test_update(self, client: TestClient, auth_headers) -> None:
        person = _person(client, auth_headers)
        response = client.patch(
            f"{API}/people/{person['id']}",
            json={"display_name": "Johnny", "timezone": "Europe/Berlin"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["display_name"] == "Johnny"
        assert response.json()["timezone"] == "Europe/Berlin"

    def test_invalid_timezone_is_rejected(
        self, client: TestClient, auth_headers
    ) -> None:
        person = _person(client, auth_headers)
        response = client.patch(
            f"{API}/people/{person['id']}",
            json={"timezone": "Mars/Olympus"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_archive_then_restore(self, client: TestClient, auth_headers) -> None:
        person = _person(client, auth_headers)
        archived = client.post(
            f"{API}/people/{person['id']}/archive", headers=auth_headers
        ).json()
        assert archived["archived_at"] is not None

        listed = client.get(f"{API}/people", headers=auth_headers).json()
        assert person["id"] not in [p["id"] for p in listed]

        with_archived = client.get(
            f"{API}/people?include_archived=true", headers=auth_headers
        ).json()
        assert person["id"] in [p["id"] for p in with_archived]

        restored = client.post(
            f"{API}/people/{person['id']}/restore", headers=auth_headers
        ).json()
        assert restored["archived_at"] is None

    def test_a_person_with_history_cannot_be_deleted(
        self, client: TestClient, auth_headers
    ) -> None:
        """Spec §5: never destroy application history."""
        person = _person(client, auth_headers)
        _application(client, auth_headers, person["id"])

        check = client.get(
            f"{API}/people/{person['id']}/deletable", headers=auth_headers
        ).json()
        assert check["can_delete"] is False
        assert check["application_count"] == 1

        response = client.delete(f"{API}/people/{person['id']}", headers=auth_headers)
        assert response.status_code == 422
        assert "Archive" in response.json()["error"]["message"]

    def test_a_person_without_history_can_be_deleted(
        self, client: TestClient, auth_headers
    ) -> None:
        person = _person(client, auth_headers)
        assert (
            client.delete(f"{API}/people/{person['id']}", headers=auth_headers).status_code
            == 200
        )


class TestApplicationCrud:
    def test_quick_add_needs_only_three_fields(
        self, client: TestClient, auth_headers
    ) -> None:
        """Spec §50: do not require 20 fields to create an application."""
        person = _person(client, auth_headers)
        application = _application(client, auth_headers, person["id"])
        assert application["status"] == "applied"
        assert application["applied_date"] == person_today().isoformat()

    def test_missing_required_fields_gives_field_level_errors(
        self, client: TestClient, auth_headers
    ) -> None:
        response = client.post(
            f"{API}/applications", json={"company_name": "Amazon"}, headers=auth_headers
        )
        assert response.status_code == 422
        assert "fields" in response.json()["error"]["details"]

    def test_salary_range_is_validated(
        self, client: TestClient, auth_headers
    ) -> None:
        person = _person(client, auth_headers)
        response = client.post(
            f"{API}/applications",
            json={
                "person_id": person["id"],
                "company_name": "Amazon",
                "job_title": "Engineer",
                "salary_min": 200000,
                "salary_max": 100000,
            },
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_update_and_status_change(self, client: TestClient, auth_headers) -> None:
        person = _person(client, auth_headers)
        application = _application(client, auth_headers, person["id"])

        updated = client.patch(
            f"{API}/applications/{application['id']}",
            json={"job_title": "Staff AI Engineer", "priority": "high"},
            headers=auth_headers,
        ).json()
        assert updated["job_title"] == "Staff AI Engineer"

        moved = client.post(
            f"{API}/applications/{application['id']}/status",
            json={"status": "interviewing"},
            headers=auth_headers,
        ).json()
        assert moved["status"] == "interviewing"
        assert moved["pipeline_column"] == "interviewing"

    def test_dropping_a_card_into_a_column_sets_a_sensible_status(
        self, client: TestClient, auth_headers
    ) -> None:
        """Spec §13: the pipeline is drag-and-drop, not a status dropdown."""
        person = _person(client, auth_headers)
        application = _application(client, auth_headers, person["id"])
        moved = client.post(
            f"{API}/applications/{application['id']}/status",
            json={"column": "final"},
            headers=auth_headers,
        ).json()
        assert moved["status"] == "final_round"
        assert moved["pipeline_column"] == "final"

    def test_archive_and_restore(self, client: TestClient, auth_headers) -> None:
        person = _person(client, auth_headers)
        application = _application(client, auth_headers, person["id"])

        client.post(f"{API}/applications/{application['id']}/archive", headers=auth_headers)
        listed = client.get(f"{API}/applications", headers=auth_headers).json()
        assert listed["total"] == 0

        client.post(f"{API}/applications/{application['id']}/restore", headers=auth_headers)
        listed = client.get(f"{API}/applications", headers=auth_headers).json()
        assert listed["total"] == 1

    def test_notes(self, client: TestClient, auth_headers) -> None:
        person = _person(client, auth_headers)
        application = _application(client, auth_headers, person["id"])

        note = client.post(
            f"{API}/applications/{application['id']}/notes",
            json={"body": "Recruiter mentioned AWS and LLM systems."},
            headers=auth_headers,
        )
        assert note.status_code == 201

        detail = client.get(
            f"{API}/applications/{application['id']}", headers=auth_headers
        ).json()
        assert len(detail["notes_log"]) == 1

    def test_missing_application_returns_a_friendly_404(
        self, client: TestClient, auth_headers
    ) -> None:
        response = client.get(f"{API}/applications/does-not-exist", headers=auth_headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "application_not_found"


class TestPersonFiltering:
    """Spec §4: the global person selector scopes the entire view."""

    @pytest.fixture
    def cast(self, client: TestClient, auth_headers) -> dict[str, dict]:
        john = _person(client, auth_headers, "John Carter")
        david = _person(client, auth_headers, "David Okafor")
        sarah = _person(client, auth_headers, "Sarah Lindqvist")
        _application(client, auth_headers, john["id"], "Amazon")
        _application(client, auth_headers, john["id"], "NVIDIA")
        _application(client, auth_headers, david["id"], "Microsoft")
        _application(client, auth_headers, sarah["id"], "Spotify")
        return {"john": john, "david": david, "sarah": sarah}

    def test_no_filter_means_everyone(
        self, client: TestClient, auth_headers, cast
    ) -> None:
        listed = client.get(f"{API}/applications", headers=auth_headers).json()
        assert listed["total"] == 4

    def test_one_person(self, client: TestClient, auth_headers, cast) -> None:
        listed = client.get(
            f"{API}/applications?person_ids={cast['john']['id']}", headers=auth_headers
        ).json()
        assert listed["total"] == 2
        assert {a["company_name"] for a in listed["items"]} == {"Amazon", "NVIDIA"}

    def test_several_people_via_repeated_parameters(
        self, client: TestClient, auth_headers, cast
    ) -> None:
        url = (
            f"{API}/applications?person_ids={cast['john']['id']}"
            f"&person_ids={cast['david']['id']}"
        )
        assert client.get(url, headers=auth_headers).json()["total"] == 3

    def test_several_people_via_a_comma_separated_parameter(
        self, client: TestClient, auth_headers, cast
    ) -> None:
        ids = f"{cast['john']['id']},{cast['sarah']['id']}"
        listed = client.get(
            f"{API}/applications?person_ids={ids}", headers=auth_headers
        ).json()
        assert listed["total"] == 3

    def test_an_unknown_id_is_ignored_rather_than_breaking_the_page(
        self, client: TestClient, auth_headers, cast
    ) -> None:
        """A stale id in localStorage must not 404 the whole dashboard."""
        ids = f"{cast['john']['id']},stale-id-from-last-week"
        listed = client.get(
            f"{API}/applications?person_ids={ids}", headers=auth_headers
        ).json()
        assert listed["total"] == 2

    def test_the_filter_applies_to_the_dashboard_too(
        self, client: TestClient, auth_headers, cast
    ) -> None:
        dashboard = client.get(
            f"{API}/dashboard?person_ids={cast['david']['id']}", headers=auth_headers
        ).json()
        metrics = {m["key"]: m["value"] for m in dashboard["metrics"]}
        assert metrics["active_applications"] == 1

    def test_the_filter_applies_to_the_pipeline_too(
        self, client: TestClient, auth_headers, cast
    ) -> None:
        pipeline = client.get(
            f"{API}/applications/pipeline?person_ids={cast['john']['id']}",
            headers=auth_headers,
        ).json()
        assert pipeline["total"] == 2


class TestSearchAndFilters:
    @pytest.fixture
    def data(self, client: TestClient, auth_headers) -> dict:
        person = _person(client, auth_headers)
        _application(
            client, auth_headers, person["id"], "Amazon", work_mode="remote", source="LinkedIn"
        )
        _application(
            client, auth_headers, person["id"], "Microsoft", work_mode="onsite", source="Referral"
        )
        return {"person": person}

    def test_search_by_company(self, client: TestClient, auth_headers, data) -> None:
        listed = client.get(f"{API}/applications?q=amaz", headers=auth_headers).json()
        assert listed["total"] == 1

    def test_filter_by_work_mode(self, client: TestClient, auth_headers, data) -> None:
        listed = client.get(
            f"{API}/applications?work_mode=remote", headers=auth_headers
        ).json()
        assert listed["total"] == 1

    def test_filter_by_source(self, client: TestClient, auth_headers, data) -> None:
        listed = client.get(
            f"{API}/applications?source=Referral", headers=auth_headers
        ).json()
        assert listed["items"][0]["company_name"] == "Microsoft"

    def test_filter_options_are_offered(
        self, client: TestClient, auth_headers, data
    ) -> None:
        options = client.get(f"{API}/applications/filter-options", headers=auth_headers).json()
        assert "LinkedIn" in options["sources"]
        assert "Amazon" in options["companies"]


class TestInterviewWorkflow:
    def test_full_journey_from_stage_to_outcome(
        self, client: TestClient, auth_headers
    ) -> None:
        person = _person(client, auth_headers)
        application = _application(client, auth_headers, person["id"])
        start = (datetime.now(UTC) + timedelta(days=2)).isoformat()

        stage = client.post(
            f"{API}/applications/{application['id']}/stages",
            json={"type_key": "technical", "events": [{"starts_at": start}]},
            headers=auth_headers,
        )
        assert stage.status_code == 201, stage.text
        body = stage.json()
        assert body["stage_badge"] == "R1 · Technical"
        assert body["status"] == "scheduled"
        assert len(body["events"]) == 1

        outcome = client.post(
            f"{API}/interview-stages/{body['id']}/outcome",
            json={"outcome": "passed", "note": "Strong on system design."},
            headers=auth_headers,
        ).json()
        assert outcome["status"] == "completed"
        assert outcome["outcome"] == "passed"

    def test_a_stage_can_hold_several_events(
        self, client: TestClient, auth_headers
    ) -> None:
        """Spec §16: a final loop is one stage with several calendar events."""
        person = _person(client, auth_headers)
        application = _application(client, auth_headers, person["id"])
        day = datetime.now(UTC) + timedelta(days=3)

        stage = client.post(
            f"{API}/applications/{application['id']}/stages",
            json={
                "type_key": "final",
                "events": [
                    {"title": "Behavioral", "starts_at": day.isoformat()},
                    {
                        "title": "System Design",
                        "starts_at": (day + timedelta(hours=2)).isoformat(),
                    },
                ],
            },
            headers=auth_headers,
        ).json()
        assert len(stage["events"]) == 2
        assert stage["events"][0]["type_label"]

    def test_upcoming_interviews_are_chronological(
        self, client: TestClient, auth_headers
    ) -> None:
        person = _person(client, auth_headers)
        application = _application(client, auth_headers, person["id"])
        later = datetime.now(UTC) + timedelta(days=5)
        sooner = datetime.now(UTC) + timedelta(days=1)

        for start in (later, sooner):
            client.post(
                f"{API}/applications/{application['id']}/stages",
                json={"type_key": "technical", "events": [{"starts_at": start.isoformat()}]},
                headers=auth_headers,
            )

        upcoming = client.get(f"{API}/interviews/upcoming", headers=auth_headers).json()
        assert len(upcoming) == 2
        assert upcoming[0]["starts_at"] < upcoming[1]["starts_at"]
        assert upcoming[0]["person_color"].startswith("#")

    def test_an_unknown_interview_type_is_rejected(
        self, client: TestClient, auth_headers
    ) -> None:
        person = _person(client, auth_headers)
        application = _application(client, auth_headers, person["id"])
        response = client.post(
            f"{API}/applications/{application['id']}/stages",
            json={"type_key": "telepathy_round"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_a_custom_interview_type_can_be_added_and_used(
        self, client: TestClient, auth_headers
    ) -> None:
        """Spec §14: allow custom interview types."""
        created = client.post(
            f"{API}/interview-types",
            json={"label": "Pair Programming", "counts_as_technical": True},
            headers=auth_headers,
        )
        assert created.status_code == 201
        key = created.json()["key"]

        person = _person(client, auth_headers)
        application = _application(client, auth_headers, person["id"])
        stage = client.post(
            f"{API}/applications/{application['id']}/stages",
            json={"type_key": key},
            headers=auth_headers,
        )
        assert stage.status_code == 201
        assert stage.json()["type_label"] == "Pair Programming"


class TestFollowUpWorkflow:
    @pytest.fixture
    def application(self, client: TestClient, auth_headers) -> dict:
        person = _person(client, auth_headers)
        return _application(client, auth_headers, person["id"])

    def test_create_complete_and_bucket(
        self, client: TestClient, auth_headers, application
    ) -> None:
        overdue = client.post(
            f"{API}/follow-ups",
            json={
                "application_id": application["id"],
                "title": "Chase the recruiter",
                "due_date": (person_today() - timedelta(days=2)).isoformat(),
            },
            headers=auth_headers,
        )
        assert overdue.status_code == 201
        assert overdue.json()["computed_status"] == "overdue"
        assert overdue.json()["days_overdue"] == 2
        assert overdue.json()["company_name"] == "Amazon"

        board = client.get(f"{API}/follow-ups/board", headers=auth_headers).json()
        assert board["counts"]["overdue"] == 1

        completed = client.post(
            f"{API}/follow-ups/{overdue.json()['id']}/complete", headers=auth_headers
        ).json()
        assert completed["computed_status"] == "completed"

        board = client.get(f"{API}/follow-ups/board", headers=auth_headers).json()
        assert board["counts"]["overdue"] == 0
        assert board["counts"]["completed"] == 1

    def test_snooze_moves_it_out_of_the_due_buckets(
        self, client: TestClient, auth_headers, application
    ) -> None:
        follow_up = client.post(
            f"{API}/follow-ups",
            json={
                "application_id": application["id"],
                "title": "Check in",
                "due_date": person_today().isoformat(),
            },
            headers=auth_headers,
        ).json()

        snoozed = client.post(
            f"{API}/follow-ups/{follow_up['id']}/snooze",
            json={"days": 5},
            headers=auth_headers,
        ).json()
        assert snoozed["computed_status"] == "snoozed"

        board = client.get(f"{API}/follow-ups/board", headers=auth_headers).json()
        assert board["counts"]["due_today"] == 0
        assert board["counts"]["snoozed"] == 1

    def test_snoozing_into_the_past_is_rejected(
        self, client: TestClient, auth_headers, application
    ) -> None:
        follow_up = client.post(
            f"{API}/follow-ups",
            json={
                "application_id": application["id"],
                "title": "Check in",
                "due_date": person_today().isoformat(),
            },
            headers=auth_headers,
        ).json()
        response = client.post(
            f"{API}/follow-ups/{follow_up['id']}/snooze",
            json={"until": (person_today() - timedelta(days=1)).isoformat()},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_an_offer_closes_outstanding_follow_ups(
        self, client: TestClient, auth_headers, application
    ) -> None:
        """Spec §21: offer received -> close interview-related follow-ups."""
        client.post(
            f"{API}/follow-ups",
            json={
                "application_id": application["id"],
                "title": "Chase the recruiter",
                "due_date": person_today().isoformat(),
            },
            headers=auth_headers,
        )
        client.post(
            f"{API}/applications/{application['id']}/status",
            json={"status": "offer"},
            headers=auth_headers,
        )
        board = client.get(f"{API}/follow-ups/board", headers=auth_headers).json()
        assert board["counts"]["due_today"] == 0
        assert board["counts"]["completed"] == 1


class TestCalendarEndpoints:
    def test_providers_are_listed_even_without_credentials(
        self, client: TestClient, auth_headers
    ) -> None:
        """Spec §69: the app must work without OAuth credentials configured."""
        providers = client.get(f"{API}/calendar/providers", headers=auth_headers).json()
        keys = {p["key"] for p in providers}
        assert keys == {"google", "microsoft"}
        for provider in providers:
            if not provider["is_configured"]:
                assert provider["missing_settings"]
                assert "env" in (provider["setup_hint"] or "")

    def test_starting_oauth_without_credentials_explains_what_is_missing(
        self, client: TestClient, auth_headers
    ) -> None:
        person = _person(client, auth_headers)
        response = client.post(
            f"{API}/calendar/oauth/google/start?person_id={person['id']}",
            headers=auth_headers,
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_not_configured"
        assert "GOOGLE_CLIENT_ID" in response.json()["error"]["details"]["missing"]

    def test_the_feed_includes_app_created_interviews(
        self, client: TestClient, auth_headers
    ) -> None:
        person = _person(client, auth_headers)
        application = _application(client, auth_headers, person["id"])
        start = datetime.now(UTC) + timedelta(days=1)
        client.post(
            f"{API}/applications/{application['id']}/stages",
            json={"type_key": "technical", "events": [{"starts_at": start.isoformat()}]},
            headers=auth_headers,
        )

        feed = client.get(f"{API}/calendar/feed", headers=auth_headers).json()
        assert len(feed["events"]) == 1
        event = feed["events"][0]
        assert event["kind"] == "interview"
        assert event["company_name"] == "Amazon"
        assert event["stage_badge"] == "R1 · Technical"
        assert event["person_color"].startswith("#")

    def test_the_feed_reports_same_person_conflicts(
        self, client: TestClient, auth_headers
    ) -> None:
        person = _person(client, auth_headers)
        first = _application(client, auth_headers, person["id"], "Amazon")
        second = _application(client, auth_headers, person["id"], "Microsoft")
        start = datetime.now(UTC) + timedelta(days=1)

        for application_id, offset in ((first["id"], 0), (second["id"], 30)):
            client.post(
                f"{API}/applications/{application_id}/stages",
                json={
                    "type_key": "technical",
                    "events": [
                        {"starts_at": (start + timedelta(minutes=offset)).isoformat()}
                    ],
                },
                headers=auth_headers,
            )

        feed = client.get(f"{API}/calendar/feed", headers=auth_headers).json()
        assert len(feed["conflicts"]) == 1
        assert feed["conflicts"][0]["overlap_minutes"] == 30


class TestSettingsAndHealth:
    def test_health_reports_provider_configuration(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert set(body["providers"]) == {"google", "microsoft"}

    def test_settings_round_trip(self, client: TestClient, auth_headers) -> None:
        updated = client.patch(
            f"{API}/settings",
            json={"sync_window_future_days": 120, "default_timezone": "Europe/Berlin"},
            headers=auth_headers,
        )
        assert updated.status_code == 200
        assert updated.json()["sync_window_future_days"] == 120
        assert updated.json()["default_timezone"] == "Europe/Berlin"

    def test_invalid_settings_are_rejected(
        self, client: TestClient, auth_headers
    ) -> None:
        response = client.patch(
            f"{API}/settings", json={"default_timezone": "Nope/Nowhere"}, headers=auth_headers
        )
        assert response.status_code == 422


def test_activity_log_records_the_story(client: TestClient, auth_headers) -> None:
    """Spec §33: a readable history, not an audit system."""
    person = _person(client, auth_headers)
    application = _application(client, auth_headers, person["id"])
    client.post(
        f"{API}/applications/{application['id']}/status",
        json={"status": "interviewing"},
        headers=auth_headers,
    )

    activity = client.get(f"{API}/activity", headers=auth_headers).json()
    messages = [entry["message"] for entry in activity["items"]]
    assert any("added Amazon" in m for m in messages)
    assert any("Applied to Interviewing" in m for m in messages)
