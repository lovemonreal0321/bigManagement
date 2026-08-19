"""Talking to the model provider when its model names change under you.

Moonshot retired `kimi-k2-0711-preview`, which had been this app's default.
Every enrichment then failed with "Not found the model … or Permission denied",
a message that names neither the setting to change nor a value to change it to.
These tests pin the recovery path: a listable set of models, and errors that
say what to do.

The provider is stubbed throughout — the suite must not need a live API key.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings, settings
from app.domains.ai import kimi
from app.domains.ai.kimi import AiError, AiNotConfiguredError

API = "/api/v1"


class _Response:
    """Just enough of `httpx.Response` for the client's error paths."""

    def __init__(self, status_code: int, payload: object, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.reason_phrase = "Error"

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "kimi_api_key", "sk-test")
    monkeypatch.setattr(settings, "ai_enabled", True)


class TestDefaults:
    def test_the_default_model_is_one_that_exists(self) -> None:
        """`kimi-k2-0711-preview` was retired; nothing should point at it."""
        assert Settings().kimi_model != "kimi-k2-0711-preview"
        assert Settings().kimi_model == "kimi-k3"

    def test_temperature_defaults_to_one(self) -> None:
        """Extraction would prefer 0.1, but current Moonshot models reject any
        value but 1 with a 400 — so the default has to be what works."""
        assert Settings().kimi_temperature == 1.0

    def test_temperature_is_configurable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An OpenAI-compatible endpoint that allows it should still be able to."""
        monkeypatch.setenv("KIMI_TEMPERATURE", "0.1")
        assert Settings().kimi_temperature == 0.1


class TestRequestPayload:
    def test_the_configured_temperature_is_sent(
        self, with_key: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: dict = {}

        class _Client:
            def __init__(self, **_): ...
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def post(self, url, json, headers):
                sent.update(json)
                return _Response(
                    200,
                    {
                        "choices": [{"message": {"content": "{}"}}],
                        "usage": {"total_tokens": 5},
                    },
                )

        monkeypatch.setattr(settings, "kimi_temperature", 1.0)
        monkeypatch.setattr(httpx, "Client", _Client)
        kimi.complete(system="s", user="u")
        assert sent["temperature"] == 1.0

    def test_an_explicit_temperature_still_wins(
        self, with_key: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: dict = {}

        class _Client:
            def __init__(self, **_): ...
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def post(self, url, json, headers):
                sent.update(json)
                return _Response(
                    200,
                    {
                        "choices": [{"message": {"content": "{}"}}],
                        "usage": {"total_tokens": 5},
                    },
                )

        monkeypatch.setattr(httpx, "Client", _Client)
        kimi.complete(system="s", user="u", temperature=0.4)
        assert sent["temperature"] == 0.4


class TestErrorsThatExplainThemselves:
    def _fail_with(self, monkeypatch: pytest.MonkeyPatch, message: str) -> None:
        class _Client:
            def __init__(self, **_): ...
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def post(self, *_, **__):
                return _Response(400, {"error": {"message": message}})

        monkeypatch.setattr(httpx, "Client", _Client)

    def test_a_retired_model_names_the_setting_and_where_to_look(
        self, with_key: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "kimi_model", "kimi-k2-0711-preview")
        self._fail_with(
            monkeypatch, "Not found the model kimi-k2-0711-preview or Permission denied"
        )

        with pytest.raises(AiError) as caught:
            kimi.complete(system="s", user="u")

        message = str(caught.value)
        assert "KIMI_MODEL" in message
        assert "kimi-k2-0711-preview" in message
        assert "/ai/models" in message
        assert caught.value.details["model"] == "kimi-k2-0711-preview"

    def test_a_rejected_temperature_names_the_setting(
        self, with_key: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._fail_with(
            monkeypatch, "invalid temperature: only 1 is allowed for this model"
        )
        with pytest.raises(AiError) as caught:
            kimi.complete(system="s", user="u")
        assert "KIMI_TEMPERATURE" in str(caught.value)

    def test_an_unrelated_error_gets_no_invented_advice(
        self, with_key: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._fail_with(monkeypatch, "context length exceeded")
        with pytest.raises(AiError) as caught:
            kimi.complete(system="s", user="u")
        message = str(caught.value)
        assert "context length exceeded" in message
        assert "KIMI_MODEL" not in message
        assert "KIMI_TEMPERATURE" not in message


class TestListModels:
    def _models(self, monkeypatch: pytest.MonkeyPatch, ids: list[str]) -> None:
        class _Client:
            def __init__(self, **_): ...
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def get(self, *_, **__):
                return _Response(200, {"data": [{"id": i} for i in ids]})

        monkeypatch.setattr(httpx, "Client", _Client)

    def test_it_returns_the_provider_list(
        self, with_key: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._models(monkeypatch, ["kimi-k2.6", "kimi-k3", "kimi-k2.7-code"])
        assert kimi.list_models() == ["kimi-k3", "kimi-k2.7-code", "kimi-k2.6"]

    def test_it_needs_a_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "kimi_api_key", "")
        with pytest.raises(AiNotConfiguredError):
            kimi.list_models()

    def test_a_bad_key_says_so(
        self, with_key: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Client:
            def __init__(self, **_): ...
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def get(self, *_, **__):
                return _Response(401, {"error": {"message": "invalid key"}})

        monkeypatch.setattr(httpx, "Client", _Client)
        with pytest.raises(AiError) as caught:
            kimi.list_models()
        assert caught.value.code == "ai_unauthorized"


class TestModelsEndpoint:
    def _models(self, monkeypatch: pytest.MonkeyPatch, ids: list[str]) -> None:
        monkeypatch.setattr(kimi, "list_models", lambda: ids)

    def test_it_flags_a_configured_model_that_is_gone(
        self, client, auth_headers, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "kimi_api_key", "sk-test")
        monkeypatch.setattr(settings, "kimi_model", "kimi-k2-0711-preview")
        self._models(monkeypatch, ["kimi-k3", "kimi-k2.6"])

        body = client.get(f"{API}/ai/models", headers=auth_headers).json()
        assert body["current"] == "kimi-k2-0711-preview"
        assert body["current_is_available"] is False
        assert body["models"] == ["kimi-k3", "kimi-k2.6"]

    def test_it_confirms_a_good_one(
        self, client, auth_headers, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "kimi_api_key", "sk-test")
        monkeypatch.setattr(settings, "kimi_model", "kimi-k3")
        self._models(monkeypatch, ["kimi-k3", "kimi-k2.6"])

        body = client.get(f"{API}/ai/models", headers=auth_headers).json()
        assert body["current_is_available"] is True

    def test_it_needs_authentication(self, client) -> None:
        assert client.get(f"{API}/ai/models").status_code == 401

    def test_it_is_administrator_only(
        self, client, auth_headers, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Consistent with the rest of the AI surface, which spends money."""
        created = client.post(
            f"{API}/users",
            json={"username": "aimodels", "password": "ai-password"},
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text
        token = client.post(
            f"{API}/auth/login",
            json={"username": "aimodels", "password": "ai-password"},
        ).json()["access_token"]

        response = client.get(
            f"{API}/ai/models", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "admin_required"
