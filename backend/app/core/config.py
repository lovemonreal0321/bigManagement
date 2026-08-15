"""Application configuration, loaded from environment / `.env`."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- app ---------------------------------------------------------------
    app_name: str = "Job Search Command Center"
    environment: str = "development"
    debug: bool = True
    api_prefix: str = "/api/v1"

    #: Port the backend binds to. 8000 is commonly taken by other local
    #: projects, so this app defaults to 8100.
    port: int = 8100
    host: str = "0.0.0.0"

    # -- database ----------------------------------------------------------
    #: SQLite lives in a file next to the backend so the whole app is portable.
    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'jobsearch.db'}"
    #: Run `alembic upgrade head` on startup. Convenient locally; turn it off if
    #: migrations should only ever be applied deliberately.
    auto_migrate: bool = True

    # -- auth --------------------------------------------------------------
    #: Fixed single-user credentials. Change these in `.env` for anything other
    #: than local use.
    admin_username: str = "admin321"
    admin_password: str = "admin321"

    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 14  # 14 days

    # -- CORS --------------------------------------------------------------
    #: Comma-separated in the environment. Kept as a plain string because
    #: pydantic-settings JSON-decodes complex types straight from `.env`, which
    #: would reject an ordinary comma-separated list before any validator ran.
    cors_origins: str = "http://localhost:3100,http://127.0.0.1:3100"

    # -- workspace defaults ------------------------------------------------
    workspace_name: str = "Job Search Command Center"
    default_timezone: str = "America/New_York"

    # -- calendar sync -----------------------------------------------------
    #: Sync window (spec §7). Configurable per connection too.
    sync_window_past_days: int = 30
    sync_window_future_days: int = 90
    #: Background sync cadence. Set to 0 to disable the scheduler entirely.
    sync_interval_minutes: int = 15
    enable_scheduler: bool = True

    # -- follow-up automation ----------------------------------------------
    followup_after_interview_business_days: int = 3
    followup_chain_business_days: int = 5
    waiting_for_feedback_threshold_days: int = 7
    no_activity_ghosted_threshold_days: int = 21

    # -- Google OAuth ------------------------------------------------------
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8100/api/v1/calendar/oauth/google/callback"

    # -- Microsoft OAuth ---------------------------------------------------
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    microsoft_tenant_id: str = "common"
    microsoft_redirect_uri: str = (
        "http://localhost:8100/api/v1/calendar/oauth/microsoft/callback"
    )

    # -- email ---------------------------------------------------------------
    #: Gmail reuses the Google OAuth client; this is only the extra scope.
    gmail_redirect_uri: str = (
        "http://localhost:8100/api/v1/email/oauth/google/callback"
    )
    #: How far around a calendar event to look for related mail.
    email_lookback_days: int = 45
    email_lookahead_days: int = 7
    #: Messages fed to the model per event, newest first. Caps cost per run.
    email_max_messages_per_event: int = 6
    #: Characters of each body kept and sent to the model.
    email_body_excerpt_chars: int = 4000

    # -- AI (Moonshot / Kimi) ------------------------------------------------
    #: OpenAI-compatible endpoint. Use https://api.moonshot.cn/v1 for keys
    #: created on the .cn platform — keys are not interchangeable.
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.ai/v1"
    kimi_model: str = "kimi-k2-0711-preview"
    kimi_timeout_seconds: float = 60.0
    kimi_max_output_tokens: int = 1200
    #: Extractions at or above this confidence create records directly; below
    #: it they wait as a suggestion.
    ai_auto_create_confidence: float = 0.75
    #: Master switch for anything that calls the model.
    ai_enabled: bool = True

    # -- frontend ----------------------------------------------------------
    #: Where to bounce the browser back to after an OAuth round-trip.
    frontend_url: str = "http://localhost:3100"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def kimi_configured(self) -> bool:
        return bool(self.ai_enabled and self.kimi_api_key)

    @property
    def secret_key_is_ephemeral(self) -> bool:
        """True when SECRET_KEY was generated at boot rather than configured.

        Stored IMAP passwords are encrypted with a key derived from it, so an
        ephemeral value means they cannot survive a restart.

        `model_fields_set` is the right test: it holds the fields that were
        actually supplied by the environment or `.env`, whereas `os.getenv`
        would miss anything read from the dotenv file.
        """
        return "secret_key" not in self.model_fields_set

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def microsoft_configured(self) -> bool:
        return bool(self.microsoft_client_id and self.microsoft_client_secret)

    @property
    def sqlite_path(self) -> Path | None:
        if self.database_url.startswith("sqlite:///"):
            return Path(self.database_url.removeprefix("sqlite:///"))
        return None


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    path = settings.sqlite_path
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
