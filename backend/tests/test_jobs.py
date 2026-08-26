"""Jobs — offers, employment, payday projection and the jobs dashboard.

A job is not an application with a different status: an application is an
opportunity being pursued, a job is income being earned. These tests pin the
places that distinction matters.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

API = "/api/v1"
PERSON_TZ = ZoneInfo("America/New_York")


def person_today() -> date:
    return datetime.now(PERSON_TZ).date()


def _person(client: TestClient, headers: dict[str, str], name: str) -> dict:
    response = client.post(f"{API}/people", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _job(client: TestClient, headers: dict[str, str], **body) -> dict:
    payload = {
        "company_name": "Anthropic",
        "title": "Senior AI Engineer",
        **body,
    }
    response = client.post(f"{API}/jobs", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def cast(client: TestClient, auth_headers: dict[str, str]) -> dict:
    john = _person(client, auth_headers, "John Carter")
    maria = _person(client, auth_headers, "Maria Lopez")
    application = client.post(
        f"{API}/applications",
        json={
            "person_id": john["id"],
            "company_name": "Anthropic",
            "job_title": "Senior AI Engineer",
        },
        headers=auth_headers,
    ).json()
    return {
        "headers": auth_headers,
        "john": john,
        "maria": maria,
        "application": application,
    }


class TestCreating:
    def test_a_job_records_the_essentials(
        self, client: TestClient, cast: dict
    ) -> None:
        job = _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            status="active",
            job_type="full_time",
            start_date="2026-09-01",
            salary_type="annual",
            annual_amount=180000,
        )
        assert job["company_name"] == "Anthropic"
        assert job["status"] == "active"
        assert job["is_live"] is True
        assert job["person_name"] == "John Carter"

    def test_an_annual_salary_derives_the_hourly_rate(
        self, client: TestClient, cast: dict
    ) -> None:
        job = _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            salary_type="annual",
            annual_amount=176800,
        )
        assert job["hourly_amount"] == 85.0

    def test_an_hourly_rate_derives_the_annual(
        self, client: TestClient, cast: dict
    ) -> None:
        job = _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            salary_type="hourly",
            hourly_amount=85,
        )
        assert job["annual_amount"] == 176800.0

    def test_a_part_time_basis_changes_the_conversion(
        self, client: TestClient, cast: dict
    ) -> None:
        job = _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            salary_type="hourly",
            hourly_amount=85,
            hours_per_week=32,
        )
        assert job["annual_amount"] == 141440.0

    def test_it_can_be_linked_to_the_application_that_won_it(
        self, client: TestClient, cast: dict
    ) -> None:
        job = _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            application_id=cast["application"]["id"],
        )
        assert job["application_id"] == cast["application"]["id"]
        assert job["application_company"] == "Anthropic"

    def test_it_refuses_an_application_belonging_to_someone_else(
        self, client: TestClient, cast: dict
    ) -> None:
        response = client.post(
            f"{API}/jobs",
            json={
                "person_id": cast["maria"]["id"],
                "company_name": "Anthropic",
                "title": "Engineer",
                "application_id": cast["application"]["id"],
            },
            headers=cast["headers"],
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "person_mismatch"

    def test_an_end_before_the_start_is_refused(
        self, client: TestClient, cast: dict
    ) -> None:
        response = client.post(
            f"{API}/jobs",
            json={
                "person_id": cast["john"]["id"],
                "company_name": "Anthropic",
                "title": "Engineer",
                "start_date": "2026-09-01",
                "end_date": "2026-08-01",
            },
            headers=cast["headers"],
        )
        assert response.status_code == 422


class TestPayday:
    def test_a_live_job_projects_upcoming_paydays(
        self, client: TestClient, cast: dict
    ) -> None:
        first = person_today() + timedelta(days=3)
        job = _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            status="active",
            salary_type="annual",
            annual_amount=104000,
            pay_period="biweekly",
            first_pay_date=first.isoformat(),
        )
        assert job["gross_per_paycheck"] == 4000.0
        assert job["next_pay_date"] == first.isoformat()
        assert len(job["upcoming_pay_dates"]) == 6
        assert job["upcoming_pay_dates"][0]["is_next"] is True
        assert job["upcoming_pay_dates"][0]["amount"] == 4000.0

    def test_semimonthly_pays_more_per_cheque_than_biweekly(
        self, client: TestClient, cast: dict
    ) -> None:
        common = {
            "person_id": cast["john"]["id"],
            "status": "active",
            "salary_type": "annual",
            "annual_amount": 104000,
            "first_pay_date": (person_today() + timedelta(days=2)).isoformat(),
        }
        semi = _job(client, cast["headers"], **common, pay_period="semimonthly")
        bi = _job(client, cast["headers"], **common, pay_period="biweekly")
        assert semi["gross_per_paycheck"] > bi["gross_per_paycheck"]

    def test_an_offer_has_no_payday_schedule(
        self, client: TestClient, cast: dict
    ) -> None:
        """An offer is not income until it is accepted."""
        job = _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            status="offered",
            annual_amount=104000,
            first_pay_date=(person_today() + timedelta(days=3)).isoformat(),
        )
        assert job["upcoming_pay_dates"] == []
        assert job["next_pay_date"] is None

    def test_past_paydays_are_skipped(self, client: TestClient, cast: dict) -> None:
        job = _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            status="active",
            annual_amount=104000,
            pay_period="weekly",
            first_pay_date="2020-01-03",
        )
        assert all(
            d["date"] > person_today().isoformat() for d in job["upcoming_pay_dates"]
        )


class TestEnding:
    def test_ending_records_the_reason(self, client: TestClient, cast: dict) -> None:
        job = _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            status="active",
            start_date="2026-01-05",
        )
        response = client.post(
            f"{API}/jobs/{job['id']}/end",
            json={"end_date": "2026-08-01", "reason": "laid_off", "note": "Team cut"},
            headers=cast["headers"],
        )
        assert response.status_code == 200, response.text
        ended = response.json()
        assert ended["status"] == "ended"
        assert ended["end_reason"] == "laid_off"
        assert ended["is_live"] is False

    def test_an_ended_job_stops_projecting_pay(
        self, client: TestClient, cast: dict
    ) -> None:
        job = _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            status="active",
            annual_amount=104000,
            first_pay_date=(person_today() + timedelta(days=2)).isoformat(),
        )
        assert job["upcoming_pay_dates"]
        ended = client.post(
            f"{API}/jobs/{job['id']}/end", json={"reason": "resigned"}, headers=cast["headers"]
        ).json()
        assert ended["upcoming_pay_dates"] == []

    def test_tenure_is_measured(self, client: TestClient, cast: dict) -> None:
        job = _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            status="active",
            start_date="2026-01-01",
        )
        ended = client.post(
            f"{API}/jobs/{job['id']}/end",
            json={"end_date": "2026-01-31"},
            headers=cast["headers"],
        ).json()
        assert ended["tenure_days"] == 30

    def test_the_history_survives(self, client: TestClient, cast: dict) -> None:
        """Losing a job must not erase that it happened."""
        job = _job(client, cast["headers"], person_id=cast["john"]["id"], status="active")
        client.post(f"{API}/jobs/{job['id']}/end", json={}, headers=cast["headers"])
        listed = client.get(f"{API}/jobs", headers=cast["headers"]).json()
        assert job["id"] in [j["id"] for j in listed]


class TestUpdating:
    def test_changing_the_rate_recomputes_the_other_figure(
        self, client: TestClient, cast: dict
    ) -> None:
        job = _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            salary_type="hourly",
            hourly_amount=85,
        )
        updated = client.patch(
            f"{API}/jobs/{job['id']}", json={"hourly_amount": 100}, headers=cast["headers"]
        ).json()
        assert updated["annual_amount"] == 208000.0

    def test_a_hand_corrected_annual_is_kept(
        self, client: TestClient, cast: dict
    ) -> None:
        """The conversion is a convenience, not a rule the user cannot override."""
        job = _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            salary_type="hourly",
            hourly_amount=85,
        )
        updated = client.patch(
            f"{API}/jobs/{job['id']}",
            json={"annual_amount": 190000},
            headers=cast["headers"],
        ).json()
        assert updated["annual_amount"] == 190000
        assert updated["hourly_amount"] == 85


class TestSummary:
    def test_only_live_jobs_count_as_income(
        self, client: TestClient, cast: dict
    ) -> None:
        _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            status="active",
            annual_amount=180000,
        )
        _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            status="offered",
            annual_amount=999999,
        )
        summary = client.get(f"{API}/jobs/summary", headers=cast["headers"]).json()
        assert summary["total_annual"] == 180000
        assert summary["live_count"] == 1
        assert summary["offered_count"] == 1

    def test_several_jobs_for_one_person_add_up(
        self, client: TestClient, cast: dict
    ) -> None:
        """Two part-time roles at once is a real situation."""
        for amount in (60000, 40000):
            _job(
                client,
                cast["headers"],
                person_id=cast["john"]["id"],
                status="active",
                job_type="part_time",
                annual_amount=amount,
            )
        summary = client.get(f"{API}/jobs/summary", headers=cast["headers"]).json()
        assert summary["total_annual"] == 100000
        john = next(p for p in summary["by_person"] if p["person_name"] == "John Carter")
        assert john["live_count"] == 2

    def test_it_reports_the_soonest_payday_across_everyone(
        self, client: TestClient, cast: dict
    ) -> None:
        soon = person_today() + timedelta(days=2)
        later = person_today() + timedelta(days=9)
        _job(
            client,
            cast["headers"],
            person_id=cast["maria"]["id"],
            status="active",
            annual_amount=104000,
            first_pay_date=later.isoformat(),
        )
        _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            status="active",
            annual_amount=104000,
            first_pay_date=soon.isoformat(),
        )
        summary = client.get(f"{API}/jobs/summary", headers=cast["headers"]).json()
        assert summary["next_pay_date"] == soon.isoformat()
        assert summary["next_pay_amount"] == 4000.0

    def test_the_person_filter_scopes_the_summary(
        self, client: TestClient, cast: dict
    ) -> None:
        _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            status="active",
            annual_amount=180000,
        )
        summary = client.get(
            f"{API}/jobs/summary",
            params={"person_ids": cast["maria"]["id"]},
            headers=cast["headers"],
        ).json()
        assert summary["total_annual"] == 0
        assert summary["live_count"] == 0


class TestPermissions:
    @pytest.fixture
    def general_user(self, client: TestClient, cast: dict) -> dict[str, str]:
        client.post(
            f"{API}/users",
            json={
                "username": "jobuser",
                "password": "job-password",
                "person_ids": [cast["john"]["id"]],
            },
            headers=cast["headers"],
        )
        token = client.post(
            f"{API}/auth/login",
            json={"username": "jobuser", "password": "job-password"},
        ).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_they_can_add_a_job_for_an_assigned_person(
        self, client: TestClient, cast: dict, general_user: dict[str, str]
    ) -> None:
        response = client.post(
            f"{API}/jobs",
            json={
                "person_id": cast["john"]["id"],
                "company_name": "Allowed Co",
                "title": "Engineer",
            },
            headers=general_user,
        )
        assert response.status_code == 201

    def test_they_cannot_for_an_unassigned_person(
        self, client: TestClient, cast: dict, general_user: dict[str, str]
    ) -> None:
        response = client.post(
            f"{API}/jobs",
            json={
                "person_id": cast["maria"]["id"],
                "company_name": "Refused Co",
                "title": "Engineer",
            },
            headers=general_user,
        )
        assert response.status_code == 403

    def test_they_can_still_read_everyone(
        self, client: TestClient, cast: dict, general_user: dict[str, str]
    ) -> None:
        _job(client, cast["headers"], person_id=cast["maria"]["id"], status="active")
        listed = client.get(f"{API}/jobs", headers=general_user).json()
        assert any(j["person_name"] == "Maria Lopez" for j in listed)

    def test_they_cannot_end_someone_elses_job(
        self, client: TestClient, cast: dict, general_user: dict[str, str]
    ) -> None:
        job = _job(
            client, cast["headers"], person_id=cast["maria"]["id"], status="active"
        )
        response = client.post(
            f"{API}/jobs/{job['id']}/end", json={}, headers=general_user
        )
        assert response.status_code == 403


class TestAnalytics:
    """The far end of the funnel: offers that became work."""

    def test_analytics_reports_the_job_outcome(
        self, client: TestClient, cast: dict
    ) -> None:
        _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            status="active",
            start_date=person_today().isoformat(),
            annual_amount=180000,
        )
        _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            status="offered",
            annual_amount=200000,
        )

        analytics = client.get(
            f"{API}/analytics", params={"period": "all_time"}, headers=cast["headers"]
        ).json()
        jobs = analytics["jobs"]
        assert jobs["live_jobs"] == 1
        assert jobs["offers_open"] == 1
        assert jobs["jobs_started"] == 1
        # An offer is not income.
        assert jobs["total_annual"] == 180000

    def test_an_ended_job_is_counted_as_ended(
        self, client: TestClient, cast: dict
    ) -> None:
        job = _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            status="active",
            start_date=person_today().isoformat(),
            annual_amount=120000,
        )
        client.post(
            f"{API}/jobs/{job['id']}/end",
            json={"end_date": person_today().isoformat(), "reason": "laid_off"},
            headers=cast["headers"],
        )
        analytics = client.get(
            f"{API}/analytics", params={"period": "all_time"}, headers=cast["headers"]
        ).json()
        assert analytics["jobs"]["jobs_ended"] == 1
        assert analytics["jobs"]["live_jobs"] == 0
        assert analytics["jobs"]["total_annual"] == 0

    def test_no_jobs_is_zeroes_not_a_missing_block(
        self, client: TestClient, cast: dict
    ) -> None:
        analytics = client.get(
            f"{API}/analytics", params={"period": "all_time"}, headers=cast["headers"]
        ).json()
        assert analytics["jobs"]["live_jobs"] == 0
        assert analytics["jobs"]["total_annual"] == 0
