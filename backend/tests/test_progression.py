"""Reaching a later round, and offers showing up where you look for them.

Two reported problems: a 1st round left sitting on "waiting" after the 2nd was
scheduled, and marking an application as an offer appearing to do nothing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

API = "/api/v1"
PERSON_TZ = ZoneInfo("America/New_York")


def person_today() -> date:
    return datetime.now(PERSON_TZ).date()


def _person(client: TestClient, headers: dict[str, str], name: str) -> dict:
    r = client.post(f"{API}/people", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _application(client, headers, person_id, company="Anthropic", **extra) -> dict:
    r = client.post(
        f"{API}/applications",
        json={
            "person_id": person_id,
            "company_name": company,
            "job_title": "Senior AI Engineer",
            **extra,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _stage(client, headers, application_id, **body) -> dict:
    r = client.post(
        f"{API}/applications/{application_id}/stages", json=body, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


def _stages(client, headers, application_id) -> list[dict]:
    return client.get(
        f"{API}/applications/{application_id}", headers=headers
    ).json()["stages"]


@pytest.fixture
def cast(client: TestClient, auth_headers: dict[str, str]) -> dict:
    john = _person(client, auth_headers, "John Carter")
    return {"headers": auth_headers, "john": john}


class TestReachingALaterRound:
    def test_an_undecided_first_round_is_marked_passed(
        self, client: TestClient, cast: dict
    ) -> None:
        """Being invited to round 2 is the answer round 1 was waiting for."""
        app = _application(client, cast["headers"], cast["john"]["id"])
        _stage(
            client,
            cast["headers"],
            app["id"],
            type_key="recruiter_screen",
            round_number=1,
            status="completed",
            outcome="waiting",
        )
        _stage(
            client,
            cast["headers"],
            app["id"],
            type_key="technical",
            round_number=2,
            status="scheduled",
        )

        stages = _stages(client, cast["headers"], app["id"])
        first = next(s for s in stages if s["round_number"] == 1)
        assert first["outcome"] == "passed"
        assert first["status"] == "completed"
        assert first["result_date"] is not None

    def test_a_pending_first_round_is_marked_passed_too(
        self, client: TestClient, cast: dict
    ) -> None:
        app = _application(client, cast["headers"], cast["john"]["id"])
        _stage(
            client,
            cast["headers"],
            app["id"],
            type_key="recruiter_screen",
            round_number=1,
            status="scheduled",
        )
        _stage(
            client, cast["headers"], app["id"], type_key="technical", round_number=2
        )
        first = next(
            s for s in _stages(client, cast["headers"], app["id"])
            if s["round_number"] == 1
        )
        assert first["outcome"] == "passed"

    def test_a_recorded_failure_is_never_overwritten(
        self, client: TestClient, cast: dict
    ) -> None:
        """A failed round followed by another is real — a re-interview, or a
        different team. The inference must not rewrite what someone recorded."""
        app = _application(client, cast["headers"], cast["john"]["id"])
        first = _stage(
            client,
            cast["headers"],
            app["id"],
            type_key="technical",
            round_number=1,
            status="completed",
            outcome="failed",
        )
        _stage(client, cast["headers"], app["id"], type_key="final", round_number=2)

        after = next(
            s for s in _stages(client, cast["headers"], app["id"])
            if s["id"] == first["id"]
        )
        assert after["outcome"] == "failed"

    def test_a_withdrawn_round_is_left_alone(
        self, client: TestClient, cast: dict
    ) -> None:
        app = _application(client, cast["headers"], cast["john"]["id"])
        first = _stage(
            client,
            cast["headers"],
            app["id"],
            type_key="technical",
            round_number=1,
            status="completed",
            outcome="withdrawn",
        )
        _stage(client, cast["headers"], app["id"], type_key="final", round_number=2)
        after = next(
            s for s in _stages(client, cast["headers"], app["id"])
            if s["id"] == first["id"]
        )
        assert after["outcome"] == "withdrawn"

    def test_a_planned_placeholder_is_not_marked_passed(
        self, client: TestClient, cast: dict
    ) -> None:
        """A round that was pencilled in and never held says nothing about
        passing — there is no evidence either way."""
        app = _application(client, cast["headers"], cast["john"]["id"])
        first = _stage(
            client,
            cast["headers"],
            app["id"],
            type_key="technical",
            round_number=1,
            status="planned",
        )
        _stage(client, cast["headers"], app["id"], type_key="final", round_number=2)
        after = next(
            s for s in _stages(client, cast["headers"], app["id"])
            if s["id"] == first["id"]
        )
        assert after["outcome"] == "pending"

    def test_every_earlier_undecided_round_is_caught(
        self, client: TestClient, cast: dict
    ) -> None:
        app = _application(client, cast["headers"], cast["john"]["id"])
        for index, key in enumerate(("recruiter_screen", "technical"), start=1):
            _stage(
                client,
                cast["headers"],
                app["id"],
                type_key=key,
                round_number=index,
                status="completed",
                outcome="waiting",
            )
        _stage(client, cast["headers"], app["id"], type_key="final", round_number=3)

        stages = _stages(client, cast["headers"], app["id"])
        assert [s["outcome"] for s in stages if s["round_number"] in (1, 2)] == [
            "passed",
            "passed",
        ]

    def test_the_inference_is_written_to_the_activity_log(
        self, client: TestClient, cast: dict
    ) -> None:
        """Never a silent rewrite of someone's data."""
        app = _application(client, cast["headers"], cast["john"]["id"])
        _stage(
            client,
            cast["headers"],
            app["id"],
            type_key="recruiter_screen",
            round_number=1,
            status="completed",
            outcome="waiting",
        )
        _stage(client, cast["headers"], app["id"], type_key="technical", round_number=2)

        entries = client.get(
            f"{API}/activity?limit=50", headers=cast["headers"]
        ).json()["items"]
        assert any(
            e["type"] == "stage_outcome_changed" and "moved on" in e["message"]
            for e in entries
        )


class TestOfferVisibility:
    def test_an_offer_on_an_older_application_still_shows_this_period(
        self, client: TestClient, cast: dict
    ) -> None:
        """The reported bug: the funnel is anchored to when the application was
        *submitted*, so marking an old one as an offer changed nothing on a
        "last 30 days" view and looked like the app ignoring you."""
        app = _application(
            client, cast["headers"], cast["john"]["id"], applied_date="2020-01-15"
        )
        client.post(
            f"{API}/applications/{app['id']}/status",
            json={"status": "offer"},
            headers=cast["headers"],
        )

        volume = client.get(
            f"{API}/analytics?period=last_30_days", headers=cast["headers"]
        ).json()["volume"]
        # Cohort-anchored: the application is far too old to be in it.
        assert volume["offers"] == 0
        # Received-anchored: the offer landed today.
        assert volume["offers_received"] == 1

    def test_the_cohort_figure_still_counts_a_fresh_application(
        self, client: TestClient, cast: dict
    ) -> None:
        app = _application(
            client,
            cast["headers"],
            cast["john"]["id"],
            applied_date=person_today().isoformat(),
        )
        client.post(
            f"{API}/applications/{app['id']}/status",
            json={"status": "offer"},
            headers=cast["headers"],
        )
        volume = client.get(
            f"{API}/analytics?period=last_30_days", headers=cast["headers"]
        ).json()["volume"]
        assert volume["offers"] == 1
        assert volume["offers_received"] == 1

    def test_an_offer_outside_the_period_is_not_counted(
        self, client: TestClient, cast: dict
    ) -> None:
        app = _application(client, cast["headers"], cast["john"]["id"])
        client.post(
            f"{API}/applications/{app['id']}/status",
            json={"status": "offer"},
            headers=cast["headers"],
        )
        volume = client.get(
            f"{API}/analytics?period=custom&start=2020-01-01&end=2020-12-31",
            headers=cast["headers"],
        ).json()["volume"]
        assert volume["offers_received"] == 0

    def test_one_application_counts_once_however_often_it_moves(
        self, client: TestClient, cast: dict
    ) -> None:
        """offer → negotiating → accepted is one offer, not three."""
        app = _application(client, cast["headers"], cast["john"]["id"])
        for status in ("offer", "negotiating", "accepted"):
            client.post(
                f"{API}/applications/{app['id']}/status",
                json={"status": status},
                headers=cast["headers"],
            )
        volume = client.get(
            f"{API}/analytics?period=last_30_days", headers=cast["headers"]
        ).json()["volume"]
        assert volume["offers_received"] == 1


class TestFutureRoundsAreLeftAlone:
    def test_a_round_booked_for_later_is_not_marked_passed(
        self, client: TestClient, cast: dict
    ) -> None:
        """Adding a third round should not declare next week's second round a
        success — it has not happened yet."""
        from datetime import timedelta

        app = _application(client, cast["headers"], cast["john"]["id"])
        future = (datetime.now(ZoneInfo("UTC")) + timedelta(days=7)).isoformat()
        upcoming = _stage(
            client,
            cast["headers"],
            app["id"],
            type_key="technical",
            round_number=1,
            status="scheduled",
            events=[{"starts_at": future}],
        )
        _stage(client, cast["headers"], app["id"], type_key="final", round_number=2)

        after = next(
            s for s in _stages(client, cast["headers"], app["id"])
            if s["id"] == upcoming["id"]
        )
        assert after["outcome"] == "pending"
        assert after["status"] == "scheduled"


class TestOffersAcrossTheDateLine:
    """The evening hole.

    A period's dates are the workspace's local ones; the activity log is in
    UTC. Comparing them directly loses the offset, so for a New York workspace
    an offer recorded after 20:00 landed on the next UTC day, past the period's
    end, and the tile read zero — four hours a day of the exact symptom this
    figure was added to cure. Rather than wait for the clock, each case moves
    the logged moment to a different hour of the same local day. Every one of
    them is today, so every one of them must count.
    """

    def _offers_received(self, client: TestClient, headers: dict[str, str]) -> int:
        response = client.get(f"{API}/analytics?period=last_30_days", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()["volume"]["offers_received"]

    @pytest.mark.parametrize("local_hour", [0, 9, 15, 20, 23])
    def test_an_offer_counts_whatever_the_hour_of_the_local_day(
        self, client: TestClient, db, cast: dict, local_hour: int
    ) -> None:
        from app.models import Activity

        app = _application(
            client, cast["headers"], cast["john"]["id"], applied_date="2020-01-15"
        )
        client.post(
            f"{API}/applications/{app['id']}/status",
            json={"status": "offer"},
            headers=cast["headers"],
        )

        moment = datetime.now(PERSON_TZ).replace(
            hour=local_hour, minute=30, second=0, microsecond=0
        )
        rows = db.query(Activity).filter(
            Activity.type == "application_status_changed"
        )
        assert rows.count() >= 1, "the status change should have been logged"
        for activity in rows:
            activity.created_at = moment.astimezone(UTC)
        db.commit()

        assert self._offers_received(client, cast["headers"]) == 1
