"""Shared HTTP helper for provider adapters.

Turns transport-level failures into `CalendarSyncError` /
`CalendarConnectionExpiredError` so the UI can show "Reconnect" versus
"Retry" without any provider-specific knowledge (spec §45, §58).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.errors import CalendarConnectionExpiredError, CalendarSyncError

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def request(
    method: str,
    url: str,
    *,
    access_token: str | None = None,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    provider: str = "calendar",
) -> dict[str, Any]:
    request_headers: dict[str, str] = {"Accept": "application/json"}
    if access_token:
        request_headers["Authorization"] = f"Bearer {access_token}"
    if headers:
        request_headers.update(headers)

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.request(
                method,
                url,
                params=params,
                json=json,
                data=data,
                headers=request_headers,
            )
    except httpx.TimeoutException as exc:
        raise CalendarSyncError(
            f"{provider.title()} took too long to respond. Please try again.",
            code="calendar_timeout",
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("%s transport error: %s", provider, exc)
        raise CalendarSyncError(
            f"Could not reach {provider.title()}. Check your connection and try again.",
            code="calendar_unreachable",
        ) from exc

    if response.status_code in (401, 403):
        # 403 can also be a scope problem, but from the user's side the fix is
        # the same: reconnect the account and grant access.
        raise CalendarConnectionExpiredError(
            f"The {provider.title()} connection is no longer authorised. "
            "Please reconnect the account.",
        )

    if response.status_code == 410:
        # Google/Graph use 410 to say "your sync token is stale" — the sync
        # engine catches this and falls back to a full re-import.
        raise CalendarSyncError(
            "The sync cursor expired; a full resync is needed.",
            code="sync_token_expired",
        )

    if response.status_code == 429:
        raise CalendarSyncError(
            f"{provider.title()} is rate limiting requests. Please try again shortly.",
            code="calendar_rate_limited",
        )

    if response.status_code >= 400:
        detail = _error_detail(response)
        logger.warning(
            "%s API error %s: %s", provider, response.status_code, detail
        )
        raise CalendarSyncError(
            f"{provider.title()} rejected the request: {detail}",
            code="calendar_api_error",
            details={"status": response.status_code},
        )

    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:  # pragma: no cover - provider returned non-JSON
        return {}


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200] or response.reason_phrase
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or error)[:200]
    if isinstance(error, str):
        return (payload.get("error_description") or error)[:200]
    return str(payload)[:200]
