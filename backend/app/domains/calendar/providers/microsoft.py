"""Microsoft Outlook / Microsoft 365 adapter (Microsoft Graph v1.0)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, ClassVar
from urllib.parse import urlencode

from app.core.config import settings
from app.core.errors import ProviderNotConfiguredError
from app.core.timeutils import UTC, get_tz, to_utc, utcnow
from app.domains.calendar.providers.base import (
    CalendarProviderAdapter,
    EventDraft,
    EventPage,
    NormalizedEvent,
    ProviderAccount,
    ProviderCalendar,
    ProviderTokens,
    extract_meeting_url,
)
from app.domains.calendar.providers.http import request
from app.enums import CalendarProvider, EventStatus

GRAPH = "https://graph.microsoft.com/v1.0"


def _authority() -> str:
    return f"https://login.microsoftonline.com/{settings.microsoft_tenant_id or 'common'}"


class MicrosoftCalendarAdapter(CalendarProviderAdapter):
    key = CalendarProvider.MICROSOFT.value
    display_name = "Microsoft Outlook"
    scopes: ClassVar[list[str]] = [
        "openid",
        "email",
        "profile",
        # `offline_access` is what makes Graph issue a refresh token.
        "offline_access",
        "User.Read",
        "Calendars.ReadWrite",
    ]

    # -- configuration -----------------------------------------------------

    @property
    def is_configured(self) -> bool:
        return settings.microsoft_configured

    def missing_settings(self) -> list[str]:
        missing = []
        if not settings.microsoft_client_id:
            missing.append("MICROSOFT_CLIENT_ID")
        if not settings.microsoft_client_secret:
            missing.append("MICROSOFT_CLIENT_SECRET")
        return missing

    def _require_configured(self) -> None:
        if not self.is_configured:
            raise ProviderNotConfiguredError(
                "Microsoft Outlook is not configured on this server. Add "
                "MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET to the backend "
                ".env file and restart.",
                details={"missing": self.missing_settings()},
            )

    # -- OAuth -------------------------------------------------------------

    def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        self._require_configured()
        params = {
            "client_id": settings.microsoft_client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": " ".join(self.scopes),
            "state": state,
        }
        return f"{_authority()}/oauth2/v2.0/authorize?{urlencode(params)}"

    def exchange_code(
        self, *, code: str, redirect_uri: str
    ) -> tuple[ProviderTokens, ProviderAccount]:
        self._require_configured()
        payload = request(
            "POST",
            f"{_authority()}/oauth2/v2.0/token",
            data={
                "client_id": settings.microsoft_client_id,
                "client_secret": settings.microsoft_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "scope": " ".join(self.scopes),
            },
            provider=self.key,
        )
        tokens = _tokens_from_payload(payload)
        profile = request(
            "GET", f"{GRAPH}/me", access_token=tokens.access_token, provider=self.key
        )
        return tokens, ProviderAccount(
            account_id=str(profile.get("id") or "unknown"),
            email=profile.get("mail") or profile.get("userPrincipalName"),
            name=profile.get("displayName"),
        )

    def refresh_tokens(self, refresh_token: str) -> ProviderTokens:
        self._require_configured()
        payload = request(
            "POST",
            f"{_authority()}/oauth2/v2.0/token",
            data={
                "client_id": settings.microsoft_client_id,
                "client_secret": settings.microsoft_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "scope": " ".join(self.scopes),
            },
            provider=self.key,
        )
        tokens = _tokens_from_payload(payload)
        tokens.refresh_token = tokens.refresh_token or refresh_token
        return tokens

    # -- calendars ---------------------------------------------------------

    def list_calendars(self, access_token: str) -> list[ProviderCalendar]:
        payload = request(
            "GET",
            f"{GRAPH}/me/calendars",
            access_token=access_token,
            params={"$top": 100},
            provider=self.key,
        )
        calendars = []
        for item in payload.get("value", []):
            calendars.append(
                ProviderCalendar(
                    id=item["id"],
                    name=item.get("name") or "Calendar",
                    description=None,
                    timezone=None,
                    color=item.get("hexColor") or None,
                    is_primary=bool(item.get("isDefaultCalendar")),
                    can_write=bool(item.get("canEdit", True)),
                )
            )
        return calendars

    # -- events ------------------------------------------------------------

    def list_events(
        self,
        access_token: str,
        *,
        calendar_id: str,
        start: datetime,
        end: datetime,
        sync_token: str | None = None,
    ) -> EventPage:
        page = EventPage()
        # Graph's delta link is a full URL, so an incremental sync just follows it.
        url = sync_token or f"{GRAPH}/me/calendars/{calendar_id}/calendarView/delta"
        params: dict[str, Any] | None = None
        if not sync_token:
            params = {
                "startDateTime": to_utc(start).isoformat().replace("+00:00", "Z"),
                "endDateTime": to_utc(end).isoformat().replace("+00:00", "Z"),
                "$top": 200,
            }

        # Ask Graph to hand back times already in UTC so no zone guessing is needed.
        headers = {"Prefer": 'outlook.timezone="UTC"'}

        while True:
            payload = request(
                "GET",
                url,
                access_token=access_token,
                params=params,
                headers=headers,
                provider=self.key,
            )
            for item in payload.get("value", []):
                if "@removed" in item:
                    page.deleted_event_ids.append(item.get("id", ""))
                    continue
                if item.get("isCancelled"):
                    page.deleted_event_ids.append(item["id"])
                    continue
                event = _normalise_event(item)
                if event is not None:
                    page.events.append(event)

            next_link = payload.get("@odata.nextLink")
            if next_link:
                url, params = next_link, None
                continue
            page.next_sync_token = payload.get("@odata.deltaLink")
            break
        return page

    def create_event(
        self, access_token: str, *, calendar_id: str, draft: EventDraft
    ) -> NormalizedEvent:
        payload = request(
            "POST",
            f"{GRAPH}/me/calendars/{calendar_id}/events",
            access_token=access_token,
            json=_draft_to_graph(draft),
            provider=self.key,
        )
        event = _normalise_event(payload)
        if event is None:  # pragma: no cover
            raise ValueError("Microsoft returned an event that could not be parsed")
        return event

    def update_event(
        self,
        access_token: str,
        *,
        calendar_id: str,
        provider_event_id: str,
        draft: EventDraft,
    ) -> NormalizedEvent:
        payload = request(
            "PATCH",
            f"{GRAPH}/me/events/{provider_event_id}",
            access_token=access_token,
            json=_draft_to_graph(draft),
            provider=self.key,
        )
        event = _normalise_event(payload)
        if event is None:  # pragma: no cover
            raise ValueError("Microsoft returned an event that could not be parsed")
        return event

    def delete_event(
        self, access_token: str, *, calendar_id: str, provider_event_id: str
    ) -> None:
        request(
            "DELETE",
            f"{GRAPH}/me/events/{provider_event_id}",
            access_token=access_token,
            provider=self.key,
        )


# --------------------------------------------------------------------------
# Payload mapping
# --------------------------------------------------------------------------


def _tokens_from_payload(payload: dict[str, Any]) -> ProviderTokens:
    expires_in = payload.get("expires_in")
    return ProviderTokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        expires_at=utcnow() + timedelta(seconds=int(expires_in)) if expires_in else None,
        scope=payload.get("scope"),
    )


def _parse_graph_time(node: dict[str, Any] | None) -> tuple[datetime | None, str | None]:
    """Graph sends `{dateTime, timeZone}` with a naive dateTime string."""
    if not node or not node.get("dateTime"):
        return None, None
    raw = node["dateTime"]
    tz_name = node.get("timeZone") or "UTC"
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=get_tz(_normalise_tz(tz_name)))
    return parsed.astimezone(UTC), tz_name


def _normalise_tz(name: str) -> str:
    """Graph may return Windows zone ids; map the common ones to IANA."""
    return _WINDOWS_TZ.get(name, name)


#: Only the zones likely to show up in practice — anything unknown falls back
#: to UTC via `get_tz`, which is safe because Graph is asked for UTC anyway.
_WINDOWS_TZ = {
    "UTC": "UTC",
    "Eastern Standard Time": "America/New_York",
    "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver",
    "Pacific Standard Time": "America/Los_Angeles",
    "GMT Standard Time": "Europe/London",
    "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Warsaw",
    "Romance Standard Time": "Europe/Paris",
    "India Standard Time": "Asia/Kolkata",
    "China Standard Time": "Asia/Shanghai",
    "Tokyo Standard Time": "Asia/Tokyo",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "Singapore Standard Time": "Asia/Singapore",
}


def _normalise_event(item: dict[str, Any]) -> NormalizedEvent | None:
    start, start_tz = _parse_graph_time(item.get("start"))
    end, end_tz = _parse_graph_time(item.get("end"))
    if start is None:
        return None
    if end is None:
        end = start + timedelta(hours=1)

    organizer = ((item.get("organizer") or {}).get("emailAddress")) or {}
    attendees = []
    for attendee in item.get("attendees", []) or []:
        address = attendee.get("emailAddress") or {}
        attendees.append(
            {
                "email": address.get("address"),
                "name": address.get("name"),
                "response": (attendee.get("status") or {}).get("response"),
                "organizer": False,
            }
        )

    body = item.get("body") or {}
    body_text = body.get("content") if body.get("contentType") == "text" else None
    preview = item.get("bodyPreview")
    location = (item.get("location") or {}).get("displayName")
    online = item.get("onlineMeeting") or {}

    status = (
        EventStatus.TENTATIVE
        if item.get("showAs") == "tentative"
        else EventStatus.CONFIRMED
    )

    return NormalizedEvent(
        provider_event_id=item["id"],
        # Graph tags an instance of a series as `occurrence` or `exception`,
        # and gives it the master's id.
        is_recurring=(
            item.get("type") in ("occurrence", "exception")
            or bool(item.get("seriesMasterId"))
        ),
        ical_uid=item.get("iCalUId"),
        etag=item.get("@odata.etag"),
        title=item.get("subject") or "(no title)",
        description=body_text or preview,
        location=location,
        meeting_url=(
            online.get("joinUrl")
            or item.get("onlineMeetingUrl")
            or extract_meeting_url(location, preview, body.get("content"))
        ),
        organizer_email=organizer.get("address"),
        organizer_name=organizer.get("name"),
        attendees=attendees,
        starts_at=start,
        ends_at=end,
        start_timezone=_normalise_tz(start_tz or "UTC"),
        end_timezone=_normalise_tz(end_tz or "UTC"),
        is_all_day=bool(item.get("isAllDay")),
        status=status,
        raw={k: v for k, v in item.items() if k != "body"},
    )


def _draft_to_graph(draft: EventDraft) -> dict[str, Any]:
    tz = draft.timezone or "UTC"
    return {
        "subject": draft.title,
        "body": {"contentType": "text", "content": draft.description or ""},
        "location": {"displayName": draft.location or ""},
        "start": {
            "dateTime": to_utc(draft.starts_at)
            .replace(tzinfo=None)
            .isoformat(timespec="seconds"),
            "timeZone": "UTC",
        },
        "end": {
            "dateTime": to_utc(draft.ends_at)
            .replace(tzinfo=None)
            .isoformat(timespec="seconds"),
            "timeZone": "UTC",
        },
        "originalStartTimeZone": tz,
    }
