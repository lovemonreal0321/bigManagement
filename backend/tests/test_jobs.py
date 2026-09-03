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
    """Jobs are the one place the workspace is not openly readable.

    Salary is need-to-know, so a job is invisible unless an administrator grants
    the account access — and a granted account sees only the profiles assigned
    to it, read-only. Managing jobs stays administrator-only.
    """

    def _make_user(
        self,
        client: TestClient,
        cast: dict,
        *,
        username: str,
        person_ids: list[str],
        can_view_jobs: bool,
    ) -> dict[str, str]:
        created = client.post(
            f"{API}/users",
            json={
                "username": username,
                "password": "job-password",
                "person_ids": person_ids,
                "can_view_jobs": can_view_jobs,
            },
            headers=cast["headers"],
        )
        assert created.status_code == 201, created.text
        assert created.json()["can_view_jobs"] is can_view_jobs
        token = client.post(
            f"{API}/auth/login",
            json={"username": username, "password": "job-password"},
        ).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    @pytest.fixture
    def denied(self, client: TestClient, cast: dict) -> dict[str, str]:
        return self._make_user(
            client,
            cast,
            username="nojobs",
            person_ids=[cast["john"]["id"]],
            can_view_jobs=False,
        )

    @pytest.fixture
    def viewer(self, client: TestClient, cast: dict) -> dict[str, str]:
        return self._make_user(
            client,
            cast,
            username="jobviewer",
            person_ids=[cast["john"]["id"]],
            can_view_jobs=True,
        )

    def test_jobs_are_invisible_by_default(
        self, client: TestClient, cast: dict, denied: dict[str, str]
    ) -> None:
        """Not an empty list — a refusal, so nothing is quietly implied."""
        for path in ("/jobs", "/jobs/summary"):
            response = client.get(f"{API}{path}", headers=denied)
            assert response.status_code == 403, f"{path}: {response.text}"
            assert response.json()["error"]["code"] == "jobs_not_permitted"

    def test_a_granted_user_sees_their_assigned_profiles(
        self, client: TestClient, cast: dict, viewer: dict[str, str]
    ) -> None:
        _job(client, cast["headers"], person_id=cast["john"]["id"], status="active")
        listed = client.get(f"{API}/jobs", headers=viewer)
        assert listed.status_code == 200, listed.text
        assert [job["person_name"] for job in listed.json()] == ["John Carter"]

    def test_a_granted_user_does_not_see_anyone_else(
        self, client: TestClient, cast: dict, viewer: dict[str, str]
    ) -> None:
        """Maria is not assigned to them, so her salary is not their business."""
        _job(client, cast["headers"], person_id=cast["maria"]["id"], status="active")
        listed = client.get(f"{API}/jobs", headers=viewer).json()
        assert listed == []

    def test_fetching_an_unassigned_job_by_id_is_a_404(
        self, client: TestClient, cast: dict, viewer: dict[str, str]
    ) -> None:
        """404 rather than 403 — a refusal would confirm the job exists."""
        job = _job(
            client, cast["headers"], person_id=cast["maria"]["id"], status="active"
        )
        response = client.get(f"{API}/jobs/{job['id']}", headers=viewer)
        assert response.status_code == 404

    def test_the_summary_is_narrowed_too(
        self, client: TestClient, cast: dict, viewer: dict[str, str]
    ) -> None:
        _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            status="active",
            annual_amount=100000,
        )
        _job(
            client,
            cast["headers"],
            person_id=cast["maria"]["id"],
            status="active",
            annual_amount=900000,
        )
        summary = client.get(f"{API}/jobs/summary", headers=viewer).json()
        assert summary["total_annual"] == 100000
        assert [p["person_name"] for p in summary["by_person"]] == ["John Carter"]

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("post", "", {"company_name": "Nope", "title": "Engineer"}),
            ("patch", "/{id}", {"title": "Renamed"}),
            ("post", "/{id}/end", {}),
            ("delete", "/{id}", None),
        ],
    )
    def test_a_granted_viewer_still_cannot_manage(
        self,
        client: TestClient,
        cast: dict,
        viewer: dict[str, str],
        method: str,
        path: str,
        body: dict | None,
    ) -> None:
        """View access is read-only, even for their own assigned profile."""
        job = _job(
            client, cast["headers"], person_id=cast["john"]["id"], status="active"
        )
        url = f"{API}/jobs{path.replace('{id}', job['id'])}"
        kwargs: dict = {"headers": viewer}
        if body is not None:
            kwargs["json"] = {**body, "person_id": cast["john"]["id"]}
        response = getattr(client, method)(url, **kwargs)
        assert response.status_code == 403, f"{method} {url} -> {response.text}"
        assert response.json()["error"]["code"] == "admin_required"

    def test_an_admin_sees_and_manages_everything(
        self, client: TestClient, cast: dict
    ) -> None:
        _job(client, cast["headers"], person_id=cast["john"]["id"], status="active")
        _job(client, cast["headers"], person_id=cast["maria"]["id"], status="active")
        listed = client.get(f"{API}/jobs", headers=cast["headers"]).json()
        assert len(listed) == 2

    def test_access_can_be_granted_and_revoked(
        self, client: TestClient, cast: dict, denied: dict[str, str]
    ) -> None:
        user_id = next(
            u["id"]
            for u in client.get(f"{API}/users", headers=cast["headers"]).json()
            if u["username"] == "nojobs"
        )
        assert client.get(f"{API}/jobs", headers=denied).status_code == 403

        client.patch(
            f"{API}/users/{user_id}",
            json={"can_view_jobs": True},
            headers=cast["headers"],
        )
        assert client.get(f"{API}/jobs", headers=denied).status_code == 200

        client.patch(
            f"{API}/users/{user_id}",
            json={"can_view_jobs": False},
            headers=cast["headers"],
        )
        assert client.get(f"{API}/jobs", headers=denied).status_code == 403

    def test_the_analytics_pay_block_follows_the_same_rule(
        self, client: TestClient, cast: dict, denied: dict[str, str], viewer: dict[str, str]
    ) -> None:
        """Otherwise salary leaks in through the analytics page instead."""
        _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            status="active",
            annual_amount=180000,
        )
        hidden = client.get(
            f"{API}/analytics", params={"period": "all_time"}, headers=denied
        ).json()
        assert hidden["jobs"] is None

        shown = client.get(
            f"{API}/analytics", params={"period": "all_time"}, headers=viewer
        ).json()
        assert shown["jobs"] is not None

    def test_a_new_account_has_no_job_access_unless_asked_for(
        self, client: TestClient, cast: dict
    ) -> None:
        created = client.post(
            f"{API}/users",
            json={"username": "plain", "password": "plain-password"},
            headers=cast["headers"],
        ).json()
        assert created["can_view_jobs"] is False


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


class TestPendingOffers:
    """The bridge from the pipeline to this page.

    The reported problem: an application marked as an offer showed up nowhere
    on Jobs, because Jobs only ever listed rows somebody had typed by hand. A
    job carries a salary and a pay period that an application cannot know, so
    reaching "offer" still does not create one — but it does surface here,
    one click from being recorded.
    """

    def _offer(
        self,
        client: TestClient,
        headers: dict[str, str],
        person_id: str,
        company: str = "Datadog",
        status: str = "offer",
    ) -> dict:
        application = client.post(
            f"{API}/applications",
            json={
                "person_id": person_id,
                "company_name": company,
                "job_title": "Staff Engineer",
            },
            headers=headers,
        ).json()
        response = client.post(
            f"{API}/applications/{application['id']}/status",
            json={"status": status},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        return application

    def _pending(self, client: TestClient, headers: dict[str, str]) -> list[dict]:
        response = client.get(f"{API}/jobs/pending-offers", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    def test_an_offer_shows_up(self, client: TestClient, cast: dict) -> None:
        self._offer(client, cast["headers"], cast["john"]["id"])
        [offer] = self._pending(client, cast["headers"])
        assert offer["company_name"] == "Datadog"
        assert offer["job_title"] == "Staff Engineer"
        assert offer["person_id"] == cast["john"]["id"]

    @pytest.mark.parametrize("status", ["offer", "negotiating", "accepted"])
    def test_every_flavour_of_offer_counts(
        self, client: TestClient, cast: dict, status: str
    ) -> None:
        # An accepted offer is still one nobody has recorded a job for, and a
        # negotiation is the moment the salary fields matter most.
        self._offer(client, cast["headers"], cast["john"]["id"], status=status)
        assert len(self._pending(client, cast["headers"])) == 1

    @pytest.mark.parametrize("status", ["applied", "interviewing", "rejected"])
    def test_anything_short_of_an_offer_does_not(
        self, client: TestClient, cast: dict, status: str
    ) -> None:
        self._offer(client, cast["headers"], cast["john"]["id"], status=status)
        assert self._pending(client, cast["headers"]) == []

    def test_it_carries_the_day_the_offer_landed(
        self, client: TestClient, cast: dict
    ) -> None:
        self._offer(client, cast["headers"], cast["john"]["id"])
        [offer] = self._pending(client, cast["headers"])
        assert offer["offered_date"] == person_today().isoformat()

    def test_recording_the_job_takes_it_off_the_list(
        self, client: TestClient, cast: dict
    ) -> None:
        application = self._offer(client, cast["headers"], cast["john"]["id"])
        assert len(self._pending(client, cast["headers"])) == 1

        _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            company_name="Datadog",
            application_id=application["id"],
        )
        assert self._pending(client, cast["headers"]) == []

    def test_a_job_recorded_without_a_link_leaves_it_listed(
        self, client: TestClient, cast: dict
    ) -> None:
        # Nothing ties the two together, so the offer is still untracked. The
        # alternative — matching on company name — would hide a second offer
        # from the same employer.
        self._offer(client, cast["headers"], cast["john"]["id"])
        _job(client, cast["headers"], person_id=cast["john"]["id"], company_name="Datadog")
        assert len(self._pending(client, cast["headers"])) == 1

    def test_two_offers_at_one_company_stay_separate(
        self, client: TestClient, cast: dict
    ) -> None:
        first = self._offer(client, cast["headers"], cast["john"]["id"])
        self._offer(client, cast["headers"], cast["john"]["id"])
        _job(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            company_name="Datadog",
            application_id=first["id"],
        )
        [remaining] = self._pending(client, cast["headers"])
        assert remaining["application_id"] != first["id"]

    def test_it_points_at_the_interview_that_won_it(
        self, client: TestClient, cast: dict
    ) -> None:
        application = self._offer(client, cast["headers"], cast["john"]["id"])
        client.post(
            f"{API}/applications/{application['id']}/stages",
            json={"type_key": "technical"},
            headers=cast["headers"],
        )
        final = client.post(
            f"{API}/applications/{application['id']}/stages",
            json={"type_key": "final"},
            headers=cast["headers"],
        )
        assert final.status_code == 201, final.text
        [offer] = self._pending(client, cast["headers"])
        assert offer["interview_stage_id"] == final.json()["id"]

    def test_it_is_scoped_like_every_other_job_read(
        self, client: TestClient, cast: dict
    ) -> None:
        """Offers name a company and a salary negotiation, so the same rule
        applies as to jobs themselves."""
        self._offer(client, cast["headers"], cast["john"]["id"])

        client.post(
            f"{API}/users",
            json={
                "username": "offerpeeker",
                "password": "job-password",
                "role": "user",
                "person_ids": [cast["john"]["id"]],
                "can_view_jobs": False,
            },
            headers=cast["headers"],
        )
        token = client.post(
            f"{API}/auth/login",
            json={"username": "offerpeeker", "password": "job-password"},
        ).json()["access_token"]

        response = client.get(
            f"{API}/jobs/pending-offers",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403, response.text
