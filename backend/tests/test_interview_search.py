"""Finding a past interview so a later round can be attached to it.

The gap this closes: an imported calendar event that is round 2 of a journey
already under way. Users remember "the Anthropic recruiter screen", not which
application row it hangs off, so the search has to match the interview itself.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

API = "/api/v1"


def _person(client: TestClient, headers: dict[str, str], name: str) -> dict:
    response = client.post(f"{API}/people", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _application(
    client: TestClient, headers: dict[str, str], person_id: str, company: str, title: str
) -> dict:
    response = client.post(
        f"{API}/applications",
        json={"person_id": person_id, "company_name": company, "job_title": title},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _stage(
    client: TestClient,
    headers: dict[str, str],
    application_id: str,
    *,
    type_key: str,
    round_number: int,
    name: str | None = None,
    starts_at: str | None = None,
) -> dict:
    payload: dict = {"type_key": type_key, "round_number": round_number}
    if name:
        payload["name"] = name
    if starts_at:
        payload["scheduled_start"] = starts_at
    response = client.post(
        f"{API}/applications/{application_id}/stages", json=payload, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _search(client: TestClient, headers: dict[str, str], **params) -> list[dict]:
    response = client.get(f"{API}/interviews/search", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def cast(client: TestClient, auth_headers: dict[str, str]) -> dict:
    john = _person(client, auth_headers, "John Carter")
    maria = _person(client, auth_headers, "Maria Lopez")

    anthropic = _application(
        client, auth_headers, john["id"], "Anthropic", "Senior AI Engineer"
    )
    stripe = _application(client, auth_headers, john["id"], "Stripe", "Staff Engineer")
    datadog = _application(client, auth_headers, maria["id"], "Datadog", "SRE")

    r1 = _stage(
        client,
        auth_headers,
        anthropic["id"],
        type_key="recruiter_screen",
        round_number=1,
        name="Recruiter Screen",
        starts_at="2026-08-17T19:00:00Z",
    )
    r2 = _stage(
        client,
        auth_headers,
        anthropic["id"],
        type_key="technical",
        round_number=2,
        name="Systems Design",
        starts_at="2026-08-24T19:00:00Z",
    )
    other = _stage(
        client,
        auth_headers,
        stripe["id"],
        type_key="technical",
        round_number=1,
        name="Coding Round",
        starts_at="2026-08-10T19:00:00Z",
    )
    maria_stage = _stage(
        client,
        auth_headers,
        datadog["id"],
        type_key="recruiter_screen",
        round_number=1,
        name="Intro Call",
    )
    return {
        "headers": auth_headers,
        "john": john,
        "maria": maria,
        "anthropic": anthropic,
        "stripe": stripe,
        "r1": r1,
        "r2": r2,
        "other": other,
        "maria_stage": maria_stage,
    }


class TestMatching:
    def test_it_matches_the_interview_name(
        self, client: TestClient, cast: dict
    ) -> None:
        """The whole point — searching by what the round was called."""
        results = _search(client, cast["headers"], q="recruiter screen")
        assert [r["stage_name"] for r in results] == ["Recruiter Screen"]

    def test_it_matches_the_company(self, client: TestClient, cast: dict) -> None:
        results = _search(client, cast["headers"], q="anthropic")
        assert {r["stage_name"] for r in results} == {"Recruiter Screen", "Systems Design"}

    def test_it_matches_the_job_title(self, client: TestClient, cast: dict) -> None:
        results = _search(client, cast["headers"], q="staff engineer")
        assert [r["company_name"] for r in results] == ["Stripe"]

    def test_matching_is_case_insensitive(
        self, client: TestClient, cast: dict
    ) -> None:
        assert len(_search(client, cast["headers"], q="ANTHROPIC")) == 2

    def test_no_query_returns_recent_interviews(
        self, client: TestClient, cast: dict
    ) -> None:
        """An empty box should still offer something to pick."""
        assert len(_search(client, cast["headers"])) == 4

    def test_nothing_matching_is_an_empty_list(
        self, client: TestClient, cast: dict
    ) -> None:
        assert _search(client, cast["headers"], q="zzzznothing") == []


class TestContext:
    def test_a_result_carries_what_the_picker_shows(
        self, client: TestClient, cast: dict
    ) -> None:
        result = next(
            r
            for r in _search(client, cast["headers"], q="anthropic")
            if r["stage_name"] == "Recruiter Screen"
        )
        assert result["company_name"] == "Anthropic"
        assert result["job_title"] == "Senior AI Engineer"
        assert result["stage_badge"] == "R1 · Recruiter"
        assert result["round_number"] == 1
        assert result["application_id"] == cast["anthropic"]["id"]
        assert result["person_id"] == cast["john"]["id"]

    def test_it_reports_the_round_a_following_interview_would_take(
        self, client: TestClient, cast: dict
    ) -> None:
        """So the link form can pre-fill "R3" without a second request."""
        results = _search(client, cast["headers"], q="anthropic")
        # Anthropic already has rounds 1 and 2.
        assert {r["next_round_number"] for r in results} == {3}

    def test_next_round_is_per_application(
        self, client: TestClient, cast: dict
    ) -> None:
        result = next(
            r for r in _search(client, cast["headers"], q="stripe")
        )
        assert result["next_round_number"] == 2

    def test_newest_interviews_come_first(
        self, client: TestClient, cast: dict
    ) -> None:
        """A follow-on round almost always attaches to something recent."""
        results = _search(client, cast["headers"])
        dated = [r for r in results if r["scheduled_start"]]
        starts = [r["scheduled_start"] for r in dated]
        assert starts == sorted(starts, reverse=True)


class TestScoping:
    def test_the_person_filter_narrows_results(
        self, client: TestClient, cast: dict
    ) -> None:
        results = _search(client, cast["headers"], person_ids=cast["maria"]["id"])
        assert [r["company_name"] for r in results] == ["Datadog"]

    def test_the_limit_is_honoured(self, client: TestClient, cast: dict) -> None:
        assert len(_search(client, cast["headers"], limit=2)) == 2

    def test_it_needs_authentication(self, client: TestClient) -> None:
        assert client.get(f"{API}/interviews/search").status_code == 401

    def test_a_general_user_can_still_search(
        self, client: TestClient, cast: dict
    ) -> None:
        """Reading is unrestricted; only writing is scoped."""
        client.post(
            f"{API}/users",
            json={
                "username": "searcher",
                "password": "search-password",
                "person_ids": [cast["john"]["id"]],
            },
            headers=cast["headers"],
        )
        token = client.post(
            f"{API}/auth/login",
            json={"username": "searcher", "password": "search-password"},
        ).json()["access_token"]
        results = _search(client, {"Authorization": f"Bearer {token}"}, q="datadog")
        assert [r["company_name"] for r in results] == ["Datadog"]
