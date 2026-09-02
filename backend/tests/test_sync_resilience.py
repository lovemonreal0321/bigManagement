"""One bad calendar must not take down the whole sync, or the whole request.

The report this comes from: `POST /calendar/sync` answered 500, and the browser
reported it as a CORS failure. Both halves are covered here — the sync should
not 500 in the first place, and a genuine 500 must still carry CORS headers so
the real error is visible rather than hidden behind a misleading one.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domains.calendar import sync as sync_service
from app.models import CalendarConnection, ExternalCalendar, Person, Workspace

API = "/api/v1"


@pytest.fixture
def connection(db: Session, workspace: Workspace, make_person) -> CalendarConnection:
    person: Person = make_person("John Carter")
    conn = CalendarConnection(
        person_id=person.id,
        provider="google",
        provider_account_id="google-john",
        account_email="john@example.com",
        status="connected",
        access_token="token",
        refresh_token="refresh",
    )
    db.add(conn)
    db.flush()
    db.add(
        ExternalCalendar(
            connection_id=conn.id,
            provider_calendar_id="primary",
            name="Primary",
            is_selected=True,
        )
    )
    db.commit()
    return conn


class _ConfiguredAdapter:
    """A provider that is set up, so the sync gets far enough to fail."""

    is_configured = True
    display_name = "Google Calendar"


@pytest.fixture
def reachable_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """The suite runs without real credentials, so the adapter would otherwise
    bail out with "not configured" long before any calendar is touched."""
    monkeypatch.setattr(sync_service, "get_adapter", lambda _: _ConfiguredAdapter())
    monkeypatch.setattr(sync_service, "ensure_access_token", lambda *a, **k: "token")


class TestOneBadCalendar:
    def test_an_unexpected_provider_error_does_not_500(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        connection: CalendarConnection,
        reachable_provider: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A provider can return anything. A surprise is a per-calendar
        problem, not a reason to fail the request."""

        def explode(*args, **kwargs):
            raise KeyError("items")

        monkeypatch.setattr(sync_service, "_sync_calendar", explode)

        response = client.post(f"{API}/calendar/sync", headers=auth_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["errors"], "the failure should be reported, not swallowed"
        assert "could not be synced" in body["errors"][0]

    def test_the_failure_is_recorded_on_the_connection(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        connection: CalendarConnection,
        db: Session,
        reachable_provider: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            sync_service,
            "_sync_calendar",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        client.post(f"{API}/calendar/sync", headers=auth_headers)

        db.expire_all()
        refreshed = db.get(CalendarConnection, connection.id)
        assert refreshed.status == "error"
        assert refreshed.last_sync_error

    def test_a_broken_connection_does_not_stop_the_others(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db: Session,
        workspace: Workspace,
        make_person,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Syncing three accounts should not be all-or-nothing."""
        for name, email in (("A One", "a@example.com"), ("B Two", "b@example.com")):
            person = make_person(name)
            conn = CalendarConnection(
                person_id=person.id,
                provider="google",
                provider_account_id=f"google-{email}",
                account_email=email,
                status="connected",
                access_token="token",
                refresh_token="refresh",
            )
            db.add(conn)
        db.commit()

        calls: list[str] = []

        def blow_up_on_the_first(db_, workspace_, conn, **kwargs):
            calls.append(conn.id)
            raise RuntimeError("connection exploded")

        monkeypatch.setattr(sync_service, "sync_connection", blow_up_on_the_first)

        response = client.post(f"{API}/calendar/sync", headers=auth_headers)
        assert response.status_code == 200, response.text
        # Both were attempted rather than the first aborting the run.
        assert len(calls) == 2
        assert len(response.json()["errors"]) == 2


class TestErrorsStillCarryCors:
    """A 500 with no Access-Control-Allow-Origin reads as a CORS fault in the
    browser, which sends you looking in entirely the wrong place."""

    @pytest.fixture(autouse=True)
    def _boom_route(self):
        from app.main import app

        router = APIRouter()

        @router.get("/__boom__")
        def boom() -> dict:
            raise RuntimeError("deliberate")

        app.include_router(router)
        yield
        app.router.routes = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) != "/__boom__"
        ]

    def test_an_unhandled_error_is_json_not_a_bare_500(
        self, client: TestClient
    ) -> None:
        response = client.get(
            "/__boom__", headers={"Origin": "http://localhost:3100"}
        )
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"

    def test_it_still_carries_the_cors_header(self, client: TestClient) -> None:
        response = client.get(
            "/__boom__", headers={"Origin": "http://localhost:3100"}
        )
        assert (
            response.headers.get("access-control-allow-origin")
            == "http://localhost:3100"
        )

    def test_no_traceback_leaks_to_the_caller(self, client: TestClient) -> None:
        """Spec §58: a friendly message, never a raw server error."""
        body = client.get(
            "/__boom__", headers={"Origin": "http://localhost:3100"}
        ).text
        assert "Traceback" not in body
        assert "deliberate" not in body
