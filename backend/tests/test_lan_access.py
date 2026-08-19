"""Reaching the app from another machine on the same network.

The failure this guards against: a teammate opens `http://192.168.3.20:3100`,
the page renders, and then spins forever because the browser's API calls are
refused. CORS is one of the two halves of that (the other is the frontend
resolving the API host at runtime — see `frontend/src/lib/api.ts`).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, settings

API = "/api/v1"


def _preflight(client: TestClient, origin: str):
    """What the browser sends before the real request."""
    return client.options(
        f"{API}/auth/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


class TestPrivateNetworkOrigins:
    @pytest.mark.parametrize(
        "origin",
        [
            # Ordinary LANs (RFC 1918)
            "http://192.168.3.20:3100",
            "http://192.168.89.128:3100",
            "http://10.0.0.5:3100",
            "http://172.16.4.9:3100",
            "http://172.31.255.254:3100",
            # Tailscale hands out CGNAT addresses
            "http://100.64.0.1:3100",
            "http://100.101.5.7:3100",
            "http://100.127.255.254:3100",
            # Cloudflare WARP / Zscaler / VM NAT use the benchmarking range.
            # A real user hit exactly this and was refused.
            "http://198.18.8.155:3100",
            "http://198.19.4.2:3100",
            # Link-local, when DHCP never answered
            "http://169.254.10.3:3100",
            # Hostnames rather than addresses
            "http://mac-mini.local:3100",
            "http://desk.lan:3100",
            "http://nas.home:3100",
            "http://build.corp.internal:3100",
        ],
    )
    def test_a_local_browser_is_allowed(self, client: TestClient, origin: str) -> None:
        response = _preflight(client, origin)
        assert response.status_code == 200, response.text
        assert response.headers.get("access-control-allow-origin") == origin

    @pytest.mark.parametrize(
        "origin",
        [
            "http://93.184.216.34:3100",  # public address
            "https://evil.example.com",
            "http://172.32.0.1:3100",  # just outside the private 172.16/12 block
            "http://192.169.3.20:3100",  # neighbouring public range
            "http://1921.68.3.20:3100",  # not an address at all
            "http://100.63.0.1:3100",  # just below the CGNAT block
            "http://100.128.0.1:3100",  # just above it
            "http://198.17.0.1:3100",  # just below the benchmarking block
            "http://198.20.0.1:3100",  # just above it
            "http://169.253.0.1:3100",  # not link-local
            "http://evil.local.example.com",  # ".local" must end the host
        ],
    )
    def test_the_wider_internet_is_not(
        self, client: TestClient, origin: str
    ) -> None:
        """The regex must not become a blanket allow-any-origin."""
        response = _preflight(client, origin)
        assert response.headers.get("access-control-allow-origin") != origin

    def test_localhost_still_works(self, client: TestClient) -> None:
        response = _preflight(client, "http://localhost:3100")
        assert response.headers.get("access-control-allow-origin") == (
            "http://localhost:3100"
        )

    def test_a_real_request_carries_the_header_too(self, client: TestClient) -> None:
        """A passing preflight is useless if the response itself is refused."""
        origin = "http://192.168.3.20:3100"
        response = client.post(
            f"{API}/auth/login",
            json={"username": "admin321", "password": "admin321"},
            headers={"Origin": origin},
        )
        assert response.status_code == 200, response.text
        assert response.headers.get("access-control-allow-origin") == origin


class TestTheSwitch:
    def test_it_can_be_turned_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "cors_allow_private_network", False)
        assert settings.cors_origin_regex is None

    def test_it_is_on_by_default(self) -> None:
        """This app is meant to be opened from the other laptop in the house."""
        assert Settings().cors_allow_private_network is True
        assert "192" in (Settings().cors_origin_regex or "")

    def test_allow_any_origin_is_off_by_default(self) -> None:
        """The escape hatch must be something you opt into deliberately."""
        assert Settings().cors_allow_any_origin is False

    def test_the_regex_is_anchored(self) -> None:
        """Unanchored, `evil.com/?x=192.168.1.1` would sail through."""
        regex = Settings().cors_origin_regex or ""
        assert regex.startswith("^") and regex.endswith("$")
