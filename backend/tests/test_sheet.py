"""The spreadsheet view of applications.

What matters here: rows land in the right day bucket, the per-day counts are
right, search narrows rows without reshuffling the tab bar, and the tabs
respect both the global person filter and who may edit what.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

API = "/api/v1"

#: `make_person` seeds people in this zone, and the backend dates applications
#: in the *person's* timezone rather than the machine's.
PERSON_TZ = ZoneInfo("America/New_York")


def person_today() -> date:
    return datetime.now(PERSON_TZ).date()


def _person(client: TestClient, headers: dict[str, str], name: str) -> dict:
    response = client.post(f"{API}/people", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _application(
    client: TestClient,
    headers: dict[str, str],
    person_id: str,
    company: str,
    *,
    applied_date: str | None = None,
    job_title: str = "Senior AI Engineer",
    job_url: str | None = None,
) -> dict:
    payload: dict = {
        "person_id": person_id,
        "company_name": company,
        "job_title": job_title,
    }
    if applied_date is not None:
        payload["applied_date"] = applied_date
    if job_url is not None:
        payload["job_url"] = job_url
    response = client.post(f"{API}/applications", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _sheet(client: TestClient, headers: dict[str, str], **params) -> dict:
    response = client.get(f"{API}/applications/sheet", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def cast(client: TestClient, auth_headers: dict[str, str]) -> dict:
    john = _person(client, auth_headers, "John Carter")
    maria = _person(client, auth_headers, "Maria Lopez")

    # Three on one day, one the day before, for John.
    for company in ("Amazon", "Stripe", "NVIDIA"):
        _application(
            client, auth_headers, john["id"], company, applied_date="2026-08-19"
        )
    _application(
        client,
        auth_headers,
        john["id"],
        "Cloudflare",
        applied_date="2026-08-18",
        job_url="https://cloudflare.com/careers/1",
    )
    # One for Maria, so the tabs are distinguishable.
    _application(client, auth_headers, maria["id"], "Datadog", applied_date="2026-08-19")

    return {"headers": auth_headers, "john": john, "maria": maria}


class TestTabs:
    def test_one_tab_per_person_with_its_own_total(
        self, client: TestClient, cast: dict
    ) -> None:
        sheet = _sheet(client, cast["headers"])
        by_name = {tab["name"]: tab for tab in sheet["tabs"]}
        assert by_name["John Carter"]["total"] == 4
        assert by_name["Maria Lopez"]["total"] == 1

    def test_tabs_carry_the_person_colour_and_initials(
        self, client: TestClient, cast: dict
    ) -> None:
        """The tab bar is the person legend in this view."""
        tab = next(t for t in _sheet(client, cast["headers"])["tabs"] if t["name"] == "John Carter")
        assert tab["initials"] == "JC"
        assert tab["color"].startswith("#")

    def test_the_first_tab_opens_by_default(
        self, client: TestClient, cast: dict
    ) -> None:
        sheet = _sheet(client, cast["headers"])
        assert sheet["person_id"] == sheet["tabs"][0]["person_id"]

    def test_an_unknown_person_id_falls_back_rather_than_404s(
        self, client: TestClient, cast: dict
    ) -> None:
        """A stale id in a bookmark should not break the page."""
        sheet = _sheet(client, cast["headers"], person_id="not-a-real-id")
        assert sheet["person_id"] == sheet["tabs"][0]["person_id"]

    def test_the_global_person_filter_narrows_the_tab_bar(
        self, client: TestClient, cast: dict
    ) -> None:
        sheet = _sheet(client, cast["headers"], person_ids=cast["maria"]["id"])
        assert [tab["name"] for tab in sheet["tabs"]] == ["Maria Lopez"]
        assert sheet["person_id"] == cast["maria"]["id"]

    def test_no_people_is_an_empty_sheet_not_an_error(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        sheet = _sheet(client, auth_headers)
        assert sheet == {
            "tabs": [],
            "person_id": None,
            "can_edit": False,
            "days": [],
            "matched": 0,
            "total": 0,
            "busiest_day": None,
            "busiest_day_count": 0,
        }


class TestDayGrouping:
    def test_rows_are_grouped_by_day_with_a_count(
        self, client: TestClient, cast: dict
    ) -> None:
        sheet = _sheet(client, cast["headers"], person_id=cast["john"]["id"])
        counts = {day["date"]: day["count"] for day in sheet["days"]}
        assert counts == {"2026-08-19": 3, "2026-08-18": 1}
        assert all(len(day["rows"]) == day["count"] for day in sheet["days"])

    def test_newest_day_first(self, client: TestClient, cast: dict) -> None:
        sheet = _sheet(client, cast["headers"], person_id=cast["john"]["id"])
        assert [day["date"] for day in sheet["days"]] == ["2026-08-19", "2026-08-18"]

    def test_the_day_label_is_rendered_server_side(
        self, client: TestClient, cast: dict
    ) -> None:
        """One place decides the wording, and it must not use `%-d`, which
        raises on Windows."""
        sheet = _sheet(client, cast["headers"], person_id=cast["john"]["id"])
        assert sheet["days"][0]["label"] == "Wed 19 Aug 2026"
        assert sheet["days"][1]["label"] == "Tue 18 Aug 2026"

    def test_undated_rows_get_their_own_bucket_at_the_bottom(
        self, client: TestClient, cast: dict
    ) -> None:
        """A saved-but-not-applied row would otherwise vanish from a
        date-grouped view."""
        response = client.post(
            f"{API}/applications",
            json={
                "person_id": cast["john"]["id"],
                "company_name": "Undated Co",
                "job_title": "Engineer",
                "status": "saved",
            },
            headers=cast["headers"],
        )
        assert response.status_code == 201, response.text

        sheet = _sheet(client, cast["headers"], person_id=cast["john"]["id"])
        last = sheet["days"][-1]
        assert last["date"] is None
        assert last["label"] == "No date recorded"
        assert [row["company_name"] for row in last["rows"]] == ["Undated Co"]

    def test_busiest_day_is_reported(self, client: TestClient, cast: dict) -> None:
        sheet = _sheet(client, cast["headers"], person_id=cast["john"]["id"])
        assert sheet["busiest_day"] == "2026-08-19"
        assert sheet["busiest_day_count"] == 3

    def test_a_new_row_dates_itself_in_the_persons_timezone(
        self, client: TestClient, cast: dict
    ) -> None:
        """Not the server's zone, and not the viewer's."""
        _application(client, cast["headers"], cast["john"]["id"], "Today Inc")
        sheet = _sheet(client, cast["headers"], person_id=cast["john"]["id"])
        today = person_today().isoformat()
        bucket = next(day for day in sheet["days"] if day["date"] == today)
        assert "Today Inc" in [row["company_name"] for row in bucket["rows"]]


class TestSearch:
    def test_a_few_letters_narrow_the_rows(
        self, client: TestClient, cast: dict
    ) -> None:
        sheet = _sheet(client, cast["headers"], person_id=cast["john"]["id"], q="ama")
        companies = [row["company_name"] for day in sheet["days"] for row in day["rows"]]
        assert companies == ["Amazon"]

    def test_search_is_case_insensitive(self, client: TestClient, cast: dict) -> None:
        sheet = _sheet(client, cast["headers"], person_id=cast["john"]["id"], q="STRIPE")
        assert sheet["matched"] == 1

    def test_day_counts_reflect_the_search(
        self, client: TestClient, cast: dict
    ) -> None:
        """The count has to describe what is on screen, or it is a lie."""
        sheet = _sheet(client, cast["headers"], person_id=cast["john"]["id"], q="ama")
        assert [day["count"] for day in sheet["days"]] == [1]

    def test_total_ignores_the_search_so_the_tabs_hold_still(
        self, client: TestClient, cast: dict
    ) -> None:
        sheet = _sheet(client, cast["headers"], person_id=cast["john"]["id"], q="ama")
        assert sheet["matched"] == 1
        assert sheet["total"] == 4
        assert next(t for t in sheet["tabs"] if t["name"] == "John Carter")["total"] == 4

    def test_search_also_matches_the_job_title(
        self, client: TestClient, cast: dict
    ) -> None:
        _application(
            client,
            cast["headers"],
            cast["john"]["id"],
            "Figma",
            job_title="Product Designer",
        )
        sheet = _sheet(client, cast["headers"], person_id=cast["john"]["id"], q="designer")
        assert sheet["matched"] == 1

    def test_no_match_is_an_empty_sheet_not_an_error(
        self, client: TestClient, cast: dict
    ) -> None:
        sheet = _sheet(
            client, cast["headers"], person_id=cast["john"]["id"], q="zzzznothing"
        )
        assert sheet["days"] == []
        assert sheet["matched"] == 0
        assert sheet["total"] == 4


class TestRowContents:
    def test_a_row_carries_what_the_columns_need(
        self, client: TestClient, cast: dict
    ) -> None:
        sheet = _sheet(client, cast["headers"], person_id=cast["john"]["id"])
        row = next(
            r
            for day in sheet["days"]
            for r in day["rows"]
            if r["company_name"] == "Cloudflare"
        )
        assert row["applied_date"] == "2026-08-18"
        assert row["job_url"] == "https://cloudflare.com/careers/1"
        assert row["job_title"] == "Senior AI Engineer"
        assert row["is_archived"] is False

    def test_archived_rows_are_hidden_unless_asked_for(
        self, client: TestClient, cast: dict
    ) -> None:
        target = next(
            r
            for day in _sheet(client, cast["headers"], person_id=cast["john"]["id"])["days"]
            for r in day["rows"]
            if r["company_name"] == "Amazon"
        )
        client.post(f"{API}/applications/{target['id']}/archive", headers=cast["headers"])

        hidden = _sheet(client, cast["headers"], person_id=cast["john"]["id"])
        assert hidden["total"] == 3
        assert "Amazon" not in [
            r["company_name"] for day in hidden["days"] for r in day["rows"]
        ]

        shown = _sheet(
            client,
            cast["headers"],
            person_id=cast["john"]["id"],
            include_archived=True,
        )
        amazon = next(
            r for day in shown["days"] for r in day["rows"] if r["company_name"] == "Amazon"
        )
        assert amazon["is_archived"] is True


class TestPermissions:
    @pytest.fixture
    def general_user(self, client: TestClient, cast: dict) -> dict[str, str]:
        """A user who may edit John's sheet but not Maria's."""
        created = client.post(
            f"{API}/users",
            json={
                "username": "sheetuser",
                "password": "sheet-password",
                "person_ids": [cast["john"]["id"]],
            },
            headers=cast["headers"],
        )
        assert created.status_code == 201, created.text
        token = client.post(
            f"{API}/auth/login",
            json={"username": "sheetuser", "password": "sheet-password"},
        ).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_tabs_say_which_sheets_are_writable(
        self, client: TestClient, cast: dict, general_user: dict[str, str]
    ) -> None:
        sheet = _sheet(client, general_user)
        editable = {tab["name"]: tab["can_edit"] for tab in sheet["tabs"]}
        assert editable == {"John Carter": True, "Maria Lopez": False}

    def test_an_unassigned_sheet_is_readable_but_not_writable(
        self, client: TestClient, cast: dict, general_user: dict[str, str]
    ) -> None:
        sheet = _sheet(client, general_user, person_id=cast["maria"]["id"])
        assert sheet["can_edit"] is False
        assert [r["company_name"] for day in sheet["days"] for r in day["rows"]] == [
            "Datadog"
        ]

    def test_an_assigned_sheet_is_writable(
        self, client: TestClient, cast: dict, general_user: dict[str, str]
    ) -> None:
        assert _sheet(client, general_user, person_id=cast["john"]["id"])["can_edit"]

    def test_an_admin_may_edit_every_sheet(
        self, client: TestClient, cast: dict
    ) -> None:
        sheet = _sheet(client, cast["headers"])
        assert all(tab["can_edit"] for tab in sheet["tabs"])


class TestCellEdits:
    """The sheet writes through the ordinary application endpoints."""

    def test_editing_the_date_moves_the_row_to_another_day(
        self, client: TestClient, cast: dict
    ) -> None:
        row = next(
            r
            for day in _sheet(client, cast["headers"], person_id=cast["john"]["id"])["days"]
            for r in day["rows"]
            if r["company_name"] == "Cloudflare"
        )
        response = client.patch(
            f"{API}/applications/{row['id']}",
            json={"applied_date": "2026-08-19"},
            headers=cast["headers"],
        )
        assert response.status_code == 200, response.text

        sheet = _sheet(client, cast["headers"], person_id=cast["john"]["id"])
        assert {day["date"]: day["count"] for day in sheet["days"]} == {"2026-08-19": 4}

    def test_editing_the_company_and_link_sticks(
        self, client: TestClient, cast: dict
    ) -> None:
        row = next(
            r
            for day in _sheet(client, cast["headers"], person_id=cast["john"]["id"])["days"]
            for r in day["rows"]
            if r["company_name"] == "Stripe"
        )
        client.patch(
            f"{API}/applications/{row['id']}",
            json={"company_name": "Stripe Inc.", "job_url": "https://stripe.com/jobs/9"},
            headers=cast["headers"],
        )
        updated = next(
            r
            for day in _sheet(client, cast["headers"], person_id=cast["john"]["id"])["days"]
            for r in day["rows"]
            if r["id"] == row["id"]
        )
        assert updated["company_name"] == "Stripe Inc."
        assert updated["job_url"] == "https://stripe.com/jobs/9"
