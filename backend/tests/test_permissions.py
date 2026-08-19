"""Roles, the recovery password, and per-profile edit scoping.

The rule under test throughout: everyone reads everything, but a non-admin
writes only to the profiles assigned to them.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import User

API = "/api/v1"

#: The recovery password the workspace owner chose. Shipped as a bcrypt hash in
#: `config.py`; the plaintext lives here only so the test can exercise it.
SUPER_PASSWORD = "onlyforMoney1!"


def _headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(
        f"{API}/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _person(client: TestClient, headers: dict[str, str], name: str) -> dict:
    response = client.post(f"{API}/people", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _application(
    client: TestClient, headers: dict[str, str], person_id: str, company: str = "Amazon"
) -> dict:
    response = client.post(
        f"{API}/applications",
        json={
            "person_id": person_id,
            "company_name": company,
            "job_title": "Senior AI Engineer",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def cast(client: TestClient, auth_headers: dict[str, str]) -> dict:
    """An admin, a general user, and two profiles — one assigned, one not."""
    mine = _person(client, auth_headers, "John Carter")
    theirs = _person(client, auth_headers, "Maria Lopez")

    created = client.post(
        f"{API}/users",
        json={
            "username": "casey",
            "password": "casey-password",
            "display_name": "Casey",
            "person_ids": [mine["id"]],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    return {
        "admin_headers": auth_headers,
        "user_headers": _headers(client, "casey", "casey-password"),
        "user": created.json(),
        "mine": mine,
        "theirs": theirs,
    }


class TestSeededAdmin:
    def test_the_bootstrapped_account_is_an_admin(self, client: TestClient) -> None:
        headers = _headers(client, "admin321", "admin321")
        me = client.get(f"{API}/auth/me", headers=headers).json()
        assert me["role"] == "admin"

    def test_env_password_seeds_but_does_not_re_apply(
        self, client: TestClient, db: Session
    ) -> None:
        """A changed admin password must survive the next startup.

        `ensure_bootstrap` runs on every boot. It used to re-sync the password
        from `.env`, which silently reverted any change made in the UI.
        """
        from app.domains.auth.service import ensure_bootstrap

        headers = _headers(client, "admin321", "admin321")
        changed = client.post(
            f"{API}/auth/password",
            json={"current_password": "admin321", "new_password": "brand-new-pw"},
            headers=headers,
        )
        assert changed.status_code == 200, changed.text

        ensure_bootstrap(db)  # simulate a restart

        assert (
            client.post(
                f"{API}/auth/login",
                json={"username": "admin321", "password": "admin321"},
            ).status_code
            == 401
        )
        _headers(client, "admin321", "brand-new-pw")  # asserts 200


class TestSuperPassword:
    def test_it_signs_an_admin_in_whatever_their_own_password_is(
        self, client: TestClient
    ) -> None:
        headers = _headers(client, "admin321", "admin321")
        client.post(
            f"{API}/auth/password",
            json={"current_password": "admin321", "new_password": "something-else"},
            headers=headers,
        )
        # The whole point: still works after the password changed.
        recovered = _headers(client, "admin321", SUPER_PASSWORD)
        assert client.get(f"{API}/auth/me", headers=recovered).json()["role"] == "admin"

    def test_it_does_not_work_for_a_general_user(
        self, client: TestClient, cast: dict
    ) -> None:
        """Recovery is an admin affair. It must not become a backdoor into
        every account in the workspace."""
        response = client.post(
            f"{API}/auth/login",
            json={"username": "casey", "password": SUPER_PASSWORD},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"

    def test_using_it_is_recorded(self, client: TestClient, cast: dict) -> None:
        _headers(client, "admin321", SUPER_PASSWORD)
        activities = client.get(
            f"{API}/activity?limit=50", headers=cast["admin_headers"]
        ).json()
        entries = activities["items"]
        assert any(
            entry["type"] == "security_event" and "recovery" in entry["message"]
            for entry in entries
        ), entries

    def test_it_can_be_turned_off(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "super_password_enabled", False)
        response = client.post(
            f"{API}/auth/login",
            json={"username": "admin321", "password": SUPER_PASSWORD},
        )
        assert response.status_code == 401

    def test_an_env_override_replaces_the_shipped_one(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "super_password", "a-different-recovery-pw")
        assert (
            client.post(
                f"{API}/auth/login",
                json={"username": "admin321", "password": SUPER_PASSWORD},
            ).status_code
            == 401
        )
        _headers(client, "admin321", "a-different-recovery-pw")  # asserts 200

    def test_it_is_accepted_when_changing_a_forgotten_password(
        self, client: TestClient
    ) -> None:
        headers = _headers(client, "admin321", SUPER_PASSWORD)
        response = client.post(
            f"{API}/auth/password",
            json={"current_password": SUPER_PASSWORD, "new_password": "chosen-by-me"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        _headers(client, "admin321", "chosen-by-me")

    def test_the_plaintext_is_not_in_the_source(self) -> None:
        """`config.py` is committed, so it may only ever hold the hash."""
        from pathlib import Path

        import app.core.config as config_module

        source = Path(config_module.__file__).read_text(encoding="utf-8")
        assert SUPER_PASSWORD not in source


class TestReadAccessIsOpen:
    """A general user sees the whole workspace — that is the point of it."""

    def test_they_can_list_everyone(self, client: TestClient, cast: dict) -> None:
        people = client.get(f"{API}/people", headers=cast["user_headers"]).json()
        names = {p["name"] for p in people}
        assert {"John Carter", "Maria Lopez"} <= names

    def test_they_can_read_an_unassigned_persons_application(
        self, client: TestClient, cast: dict
    ) -> None:
        application = _application(
            client, cast["admin_headers"], cast["theirs"]["id"], company="Stripe"
        )
        response = client.get(
            f"{API}/applications/{application['id']}", headers=cast["user_headers"]
        )
        assert response.status_code == 200
        assert response.json()["company_name"] == "Stripe"

    def test_analytics_and_calendar_stay_visible(
        self, client: TestClient, cast: dict
    ) -> None:
        for path in ("/analytics", "/analytics/workload", "/calendar/feed", "/dashboard"):
            response = client.get(f"{API}{path}", headers=cast["user_headers"])
            assert response.status_code == 200, f"{path}: {response.text}"


class TestWriteScoping:
    def test_they_can_edit_an_assigned_profiles_application(
        self, client: TestClient, cast: dict
    ) -> None:
        application = _application(client, cast["user_headers"], cast["mine"]["id"])
        response = client.patch(
            f"{API}/applications/{application['id']}",
            json={"job_title": "Staff AI Engineer"},
            headers=cast["user_headers"],
        )
        assert response.status_code == 200, response.text
        assert response.json()["job_title"] == "Staff AI Engineer"

    def test_they_cannot_create_for_an_unassigned_profile(
        self, client: TestClient, cast: dict
    ) -> None:
        response = client.post(
            f"{API}/applications",
            json={
                "person_id": cast["theirs"]["id"],
                "company_name": "Netflix",
                "job_title": "Engineer",
            },
            headers=cast["user_headers"],
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "person_not_assigned"

    def test_they_cannot_edit_an_unassigned_profiles_application(
        self, client: TestClient, cast: dict
    ) -> None:
        application = _application(
            client, cast["admin_headers"], cast["theirs"]["id"]
        )
        for method, path, body in (
            ("patch", f"/applications/{application['id']}", {"job_title": "x"}),
            (
                "post",
                f"/applications/{application['id']}/status",
                {"status": "interviewing"},
            ),
            ("post", f"/applications/{application['id']}/archive", None),
            ("delete", f"/applications/{application['id']}", None),
            ("post", f"/applications/{application['id']}/notes", {"body": "hi"}),
        ):
            call = getattr(client, method)
            kwargs = {"headers": cast["user_headers"]}
            if body is not None:
                kwargs["json"] = body
            response = call(f"{API}{path}", **kwargs)
            assert response.status_code == 403, f"{method} {path} -> {response.text}"

    def test_interview_stages_follow_the_application(
        self, client: TestClient, cast: dict
    ) -> None:
        theirs = _application(client, cast["admin_headers"], cast["theirs"]["id"])
        response = client.post(
            f"{API}/applications/{theirs['id']}/stages",
            json={"type_key": "technical", "sequence": 1},
            headers=cast["user_headers"],
        )
        assert response.status_code == 403

        mine = _application(client, cast["user_headers"], cast["mine"]["id"])
        allowed = client.post(
            f"{API}/applications/{mine['id']}/stages",
            json={"type_key": "technical", "sequence": 1},
            headers=cast["user_headers"],
        )
        assert allowed.status_code == 201, allowed.text

    def test_follow_ups_follow_the_application(
        self, client: TestClient, cast: dict
    ) -> None:
        theirs = _application(client, cast["admin_headers"], cast["theirs"]["id"])
        response = client.post(
            f"{API}/follow-ups",
            json={
                "application_id": theirs["id"],
                "title": "Check in with the recruiter",
                "due_date": "2026-09-01",
            },
            headers=cast["user_headers"],
        )
        assert response.status_code == 403

    def test_an_admin_is_not_scoped(self, client: TestClient, cast: dict) -> None:
        """The workspace owner asked for admin to have any access."""
        for person in (cast["mine"], cast["theirs"]):
            _application(
                client, cast["admin_headers"], person["id"], company="Anywhere"
            )

    def test_a_missing_record_still_reads_as_missing(
        self, client: TestClient, cast: dict
    ) -> None:
        """404 must not become 403 — an unknown id is not a permission hint."""
        response = client.patch(
            f"{API}/applications/does-not-exist",
            json={"job_title": "x"},
            headers=cast["user_headers"],
        )
        assert response.status_code == 404


class TestAdminOnlyAreas:
    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("post", "/people", {"name": "New Person"}),
            ("patch", "/settings", {"sync_window_past_days": 45}),
            ("post", "/interview-types", {"label": "Coffee chat"}),
            ("post", "/ai/enrich", {}),
            ("get", "/users", None),
            (
                "post",
                "/users",
                {"username": "intruder", "password": "password123"},
            ),
        ],
    )
    def test_a_general_user_is_refused(
        self, client: TestClient, cast: dict, method: str, path: str, body: dict | None
    ) -> None:
        kwargs = {"headers": cast["user_headers"]}
        if body is not None:
            kwargs["json"] = body
        response = getattr(client, method)(f"{API}{path}", **kwargs)
        assert response.status_code == 403, f"{method} {path} -> {response.text}"
        assert response.json()["error"]["code"] == "admin_required"

    def test_renaming_their_own_assigned_profile_is_still_admin_only(
        self, client: TestClient, cast: dict
    ) -> None:
        """Assignment grants edit rights over a person's *records*, not over
        the profile itself — colours and names are workspace-level."""
        response = client.patch(
            f"{API}/people/{cast['mine']['id']}",
            json={"display_name": "Johnny"},
            headers=cast["user_headers"],
        )
        assert response.status_code == 403


class TestUserManagement:
    def test_an_admin_creates_assigns_and_the_user_can_sign_in(
        self, client: TestClient, cast: dict
    ) -> None:
        assert cast["user"]["assigned_person_ids"] == [cast["mine"]["id"]]
        assert cast["user"]["role"] == "user"
        me = client.get(f"{API}/auth/me", headers=cast["user_headers"]).json()
        assert me["assigned_person_ids"] == [cast["mine"]["id"]]

    def test_a_new_account_is_flagged_to_change_its_password(
        self, client: TestClient, cast: dict
    ) -> None:
        """The admin picked that password, so the user should replace it."""
        assert cast["user"]["must_change_password"] is True
        client.post(
            f"{API}/auth/password",
            json={
                "current_password": "casey-password",
                "new_password": "only-i-know-this",
            },
            headers=cast["user_headers"],
        )
        me = client.get(
            f"{API}/auth/me", headers=_headers(client, "casey", "only-i-know-this")
        ).json()
        assert me["must_change_password"] is False

    def test_assignment_is_multi_select_and_replaces(
        self, client: TestClient, cast: dict
    ) -> None:
        response = client.put(
            f"{API}/users/{cast['user']['id']}/people",
            json={"person_ids": [cast["mine"]["id"], cast["theirs"]["id"]]},
            headers=cast["admin_headers"],
        )
        assert response.status_code == 200, response.text
        assert set(response.json()["assigned_person_ids"]) == {
            cast["mine"]["id"],
            cast["theirs"]["id"],
        }

        # Now the previously forbidden write succeeds.
        _application(client, _headers(client, "casey", "casey-password"), cast["theirs"]["id"])

        cleared = client.put(
            f"{API}/users/{cast['user']['id']}/people",
            json={"person_ids": []},
            headers=cast["admin_headers"],
        )
        assert cleared.json()["assigned_person_ids"] == []

    def test_an_admin_can_reset_someones_password(
        self, client: TestClient, cast: dict
    ) -> None:
        response = client.put(
            f"{API}/users/{cast['user']['id']}/password",
            json={"password": "reset-by-admin"},
            headers=cast["admin_headers"],
        )
        assert response.status_code == 200, response.text
        _headers(client, "casey", "reset-by-admin")

    def test_a_disabled_account_cannot_sign_in_or_keep_using_its_token(
        self, client: TestClient, cast: dict
    ) -> None:
        still_valid = cast["user_headers"]
        client.patch(
            f"{API}/users/{cast['user']['id']}",
            json={"is_active": False},
            headers=cast["admin_headers"],
        )

        login = client.post(
            f"{API}/auth/login", json={"username": "casey", "password": "casey-password"}
        )
        assert login.status_code == 401
        assert login.json()["error"]["code"] == "account_disabled"

        # An unexpired token must stop working too, not linger for 14 days.
        assert client.get(f"{API}/auth/me", headers=still_valid).status_code == 401

    def test_promoting_a_user_grants_full_access(
        self, client: TestClient, cast: dict
    ) -> None:
        client.patch(
            f"{API}/users/{cast['user']['id']}",
            json={"role": "admin"},
            headers=cast["admin_headers"],
        )
        promoted = _headers(client, "casey", "casey-password")
        _application(client, promoted, cast["theirs"]["id"], company="Now Allowed")

    def test_duplicate_usernames_are_refused(
        self, client: TestClient, cast: dict
    ) -> None:
        response = client.post(
            f"{API}/users",
            json={"username": "casey", "password": "another-password"},
            headers=cast["admin_headers"],
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "username_taken"

    def test_the_last_admin_cannot_be_demoted_or_removed(
        self, client: TestClient, cast: dict, db: Session
    ) -> None:
        """Otherwise the workspace becomes unadministrable — and the recovery
        password would have no admin account left to unlock."""
        admin = db.query(User).filter(User.username == "admin321").one()

        demote = client.patch(
            f"{API}/users/{admin.id}",
            json={"role": "user"},
            headers=cast["admin_headers"],
        )
        assert demote.status_code == 403
        assert demote.json()["error"]["code"] == "last_admin"

        # Deleting yourself is caught first, and is its own refusal.
        deleted = client.delete(
            f"{API}/users/{admin.id}", headers=cast["admin_headers"]
        )
        assert deleted.status_code == 422
        assert deleted.json()["error"]["code"] == "cannot_delete_self"

    def test_assigning_an_unknown_profile_is_rejected(
        self, client: TestClient, cast: dict
    ) -> None:
        response = client.put(
            f"{API}/users/{cast['user']['id']}/people",
            json={"person_ids": ["not-a-real-id"]},
            headers=cast["admin_headers"],
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "unknown_person"

    def test_passwords_are_never_returned(self, client: TestClient, cast: dict) -> None:
        body = client.get(f"{API}/users", headers=cast["admin_headers"]).text
        assert "password_hash" not in body
        assert "casey-password" not in body
