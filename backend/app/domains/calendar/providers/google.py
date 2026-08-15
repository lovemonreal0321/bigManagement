"""Google Calendar adapter (Calendar API v3)."""

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

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
CALENDAR_LIST_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
EVENT_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}"


class GoogleCalendarAdapter(CalendarProviderAdapter):
    key = CalendarProvider.GOOGLE.value
    display_name = "Google Calendar"
    scopes: ClassVar[list[str]] = [
        "openid",
        "email",
        "profile",
        # `calendar.events` covers both reading and writing events, which is
        # what write-back needs (spec §48).
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.readonly",
    ]

    # -- configuration -----------------------------------------------------

    @property
    def is_configured(self) -> bool:
        return settings.google_configured

    def missing_settings(self) -> list[str]:
        missing = []
        if not settings.google_client_id:
            missing.append("GOOGLE_CLIENT_ID")
        if not settings.google_client_secret:
            missing.append("GOOGLE_CLIENT_SECRET")
        return missing

    def _require_configured(self) -> None:
        if not self.is_configured:
            raise ProviderNotConfiguredError(
                "Google Calendar is not configured on this server. Add "
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to the backend .env "
                "file and restart.",
                details={"missing": self.missing_settings()},
            )

    # -- OAuth -------------------------------------------------------------

    def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        self._require_configured()
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "state": state,
            # `offline` + `consent` guarantee a refresh token even on a repeat
            # authorisation, which Google otherwise omits.
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(
        self, *, code: str, redirect_uri: str
    ) -> tuple[ProviderTokens, ProviderAccount]:
        self._require_configured()
        payload = request(
            "POST",
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            provider=self.key,
        )
        tokens = _tokens_from_payload(payload)
        profile = request(
            "GET", USERINFO_URL, access_token=tokens.access_token, provider=self.key
        )
        account = ProviderAccount(
            account_id=str(profile.get("sub") or profile.get("email") or "unknown"),
            email=profile.get("email"),
            name=profile.get("name"),
        )
        return tokens, account

    def refresh_tokens(self, refresh_token: str) -> ProviderTokens:
        self._require_configured()
        payload = request(
            "POST",
            TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token",
            },
            provider=self.key,
        )
        tokens = _tokens_from_payload(payload)
        # Google does not resend the refresh token on a refresh; keep the old one.
        tokens.refresh_token = tokens.refresh_token or refresh_token
        return tokens

    # -- calendars ---------------------------------------------------------

    def list_calendars(self, access_token: str) -> list[ProviderCalendar]:
        payload = request(
            "GET",
            CALENDAR_LIST_URL,
            access_token=access_token,
            params={"maxResults": 250, "showHidden": "false"},
            provider=self.key,
        )
        calendars = []
        for item in payload.get("items", []):
            role = item.get("accessRole", "reader")
            calendars.append(
                ProviderCalendar(
                    id=item["id"],
                    name=item.get("summary") or item["id"],
                    description=item.get("description"),
                    timezone=item.get("timeZone"),
                    color=item.get("backgroundColor"),
                    is_primary=bool(item.get("primary")),
                    can_write=role in ("owner", "writer"),
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
        params: dict[str, Any] = {
            "maxResults": 250,
            # Expand recurring series into individual instances so each one can
            # be classified and linked on its own.
            "singleEvents": "true",
            "showDeleted": "true",
        }
        if sync_token:
            # An incremental sync must not also send timeMin/timeMax — Google
            # rejects the combination.
            params["syncToken"] = sync_token
        else:
            params["timeMin"] = to_utc(start).isoformat().replace("+00:00", "Z")
            params["timeMax"] = to_utc(end).isoformat().replace("+00:00", "Z")
            params["orderBy"] = "startTime"

        page = EventPage()
        page_token: str | None = None
        url = EVENTS_URL.format(calendar_id=calendar_id)

        while True:
            if page_token:
                params["pageToken"] = page_token
            payload = request(
                "GET", url, access_token=access_token, params=params, provider=self.key
            )
            for item in payload.get("items", []):
                if item.get("status") == "cancelled":
                    page.deleted_event_ids.append(item["id"])
                    continue
                event = _normalise_event(item)
                if event is not None:
                    page.events.append(event)

            page_token = payload.get("nextPageToken")
            if not page_token:
                page.next_sync_token = payload.get("nextSyncToken")
                break
        return page

    def create_event(
        self, access_token: str, *, calendar_id: str, draft: EventDraft
    ) -> NormalizedEvent:
        payload = request(
            "POST",
            EVENTS_URL.format(calendar_id=calendar_id),
            access_token=access_token,
            json=_draft_to_google(draft),
            provider=self.key,
        )
        event = _normalise_event(payload)
        if event is None:  # pragma: no cover - provider echoed something odd
            raise ValueError("Google returned an event that could not be parsed")
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
            EVENT_URL.format(calendar_id=calendar_id, event_id=provider_event_id),
            access_token=access_token,
            json=_draft_to_google(draft),
            provider=self.key,
        )
        event = _normalise_event(payload)
        if event is None:  # pragma: no cover
            raise ValueError("Google returned an event that could not be parsed")
        return event

    def delete_event(
        self, access_token: str, *, calendar_id: str, provider_event_id: str
    ) -> None:
        request(
            "DELETE",
            EVENT_URL.format(calendar_id=calendar_id, event_id=provider_event_id),
            access_token=access_token,
            provider=self.key,
        )


# --------------------------------------------------------------------------
# Payload mapping
# --------------------------------------------------------------------------


def _tokens_from_payload(payload: dict[str, Any]) -> ProviderTokens:
    expires_in = payload.get("expires_in")
    expires_at = (
        utcnow() + timedelta(seconds=int(expires_in)) if expires_in else None
    )
    return ProviderTokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        expires_at=expires_at,
        scope=payload.get("scope"),
    )


def _parse_google_time(node: dict[str, Any] | None) -> tuple[datetime | None, str | None, bool]:
    """Google sends either `dateTime` (+ optional `timeZone`) or `date`."""
    if not node:
        return None, None, False
    if node.get("dateTime"):
        raw = node["dateTime"]
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        tz_name = node.get("timeZone")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=get_tz(tz_name))
        return parsed.astimezone(UTC), tz_name, False
    if node.get("date"):
        tz_name = node.get("timeZone")
        day = datetime.fromisoformat(node["date"])
        return day.replace(tzinfo=get_tz(tz_name) if tz_name else UTC), tz_name, True
    return None, None, False


def _normalise_event(item: dict[str, Any]) -> NormalizedEvent | None:
    start, start_tz, start_all_day = _parse_google_time(item.get("start"))
    end, end_tz, _ = _parse_google_time(item.get("end"))
    if start is None:
        return None
    if end is None:
        end = start + timedelta(hours=1)

    organizer = item.get("organizer") or {}
    attendees = [
        {
            "email": a.get("email"),
            "name": a.get("displayName"),
            "response": a.get("responseStatus"),
            "organizer": bool(a.get("organizer")),
        }
        for a in item.get("attendees", [])
    ]

    conference = item.get("conferenceData") or {}
    conference_url = None
    for entry in conference.get("entryPoints", []) or []:
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            conference_url = entry["uri"]
            break

    status_raw = item.get("status", "confirmed")
    status = (
        EventStatus.TENTATIVE if status_raw == "tentative" else EventStatus.CONFIRMED
    )

    return NormalizedEvent(
        provider_event_id=item["id"],
        ical_uid=item.get("iCalUID"),
        etag=item.get("etag"),
        title=item.get("summary") or "(no title)",
        description=item.get("description"),
        location=item.get("location"),
        meeting_url=(
            conference_url
            or item.get("hangoutLink")
            or extract_meeting_url(item.get("location"), item.get("description"))
        ),
        organizer_email=organizer.get("email"),
        organizer_name=organizer.get("displayName"),
        attendees=attendees,
        starts_at=start,
        ends_at=end,
        start_timezone=start_tz,
        end_timezone=end_tz,
        is_all_day=start_all_day,
        status=status,
        raw=item,
    )


def _draft_to_google(draft: EventDraft) -> dict[str, Any]:
    tz = draft.timezone or "UTC"
    return {
        "summary": draft.title,
        "description": draft.description,
        "location": draft.location,
        "start": {
            "dateTime": to_utc(draft.starts_at).isoformat().replace("+00:00", "Z"),
            "timeZone": tz,
        },
        "end": {
            "dateTime": to_utc(draft.ends_at).isoformat().replace("+00:00", "Z"),
            "timeZone": tz,
        },
    }
