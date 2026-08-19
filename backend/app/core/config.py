"""Application configuration, loaded from environment / `.env`."""

from __future__ import annotations

import contextlib
import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


def _env_file() -> Path | None:
    """Which dotenv file to read, if any.

    Overridable via `JSCC_ENV_FILE` so the test suite can opt out entirely.
    Without that, tests would inherit whatever the developer happens to have in
    `.env` — real OAuth credentials, for instance — and assertions about
    unconfigured providers would pass or fail depending on the machine.
    """
    override = os.getenv("JSCC_ENV_FILE")
    if override is None:
        return BACKEND_DIR / ".env"
    return Path(override) if override.strip() else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_file(),
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

    #: Recovery password. Always grants access to an ADMIN account, whatever
    #: that admin's own password has been changed to — so a forgotten password
    #: can never lock everyone out of the workspace.
    #:
    #: Only the bcrypt hash lives here, never the plaintext, because this file
    #: is committed to source control. Set SUPER_PASSWORD in `.env` to use a
    #: different one, or SUPER_PASSWORD_ENABLED=false to switch it off.
    super_password_hash: str = (
        "$2b$12$FCiiYq3tTtIRGkattpev7.4jIrjcWeP7H0ljKzHnAcae.0IE99mm2"
    )
    #: Plaintext override from the environment; takes precedence when set.
    super_password: str = ""
    super_password_enabled: bool = True

    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 14  # 14 days

    # -- CORS --------------------------------------------------------------
    #: Comma-separated in the environment. Kept as a plain string because
    #: pydantic-settings JSON-decodes complex types straight from `.env`, which
    #: would reject an ordinary comma-separated list before any validator ran.
    cors_origins: str = "http://localhost:3100,http://127.0.0.1:3100"

    #: Also accept browsers reaching the app over a local network, rather than
    #: only `localhost`. Without this, a teammate opening
    #: http://192.168.3.20:3100 is blocked by CORS and the page spins forever,
    #: and the fix would otherwise be to hard-code an address that changes with
    #: every DHCP lease.
    #:
    #: "Local" is wider than RFC 1918, because the address a machine actually
    #: answers on is often handed out by something else: Tailscale uses CGNAT
    #: (100.64/10), and VPN clients like Cloudflare WARP and Zscaler, as well as
    #: VM NAT, commonly use the benchmarking range 198.18/15. See
    #: `cors_origin_regex` for the full list. Routable public addresses are
    #: never matched.
    cors_allow_private_network: bool = True

    #: Last resort for a network none of the above covers. Reflects whatever
    #: origin asks, so only turn it on when the server is reachable solely by
    #: people you trust.
    #:
    #: Sessions are bearer tokens in localStorage rather than cookies, so a
    #: foreign origin cannot ride along on an existing session the way it could
    #: with cookie auth — but it still lets any page that knows the address
    #: talk to the API, so leave this off unless something is genuinely broken.
    cors_allow_any_origin: bool = False

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
    #: Outlook mail reuses the Microsoft OAuth client; only the scope differs.
    outlook_mail_redirect_uri: str = (
        "http://localhost:8100/api/v1/email/oauth/microsoft/callback"
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
    #: Moonshot retires model names fairly often — `kimi-k2-0711-preview`
    #: shipped here originally and no longer exists. `GET /api/v1/ai/models`
    #: asks the provider what this key can actually use.
    kimi_model: str = "kimi-k3"
    kimi_timeout_seconds: float = 60.0
    kimi_max_output_tokens: int = 1200
    #: Extraction wants determinism, so 0.1 would be the natural choice — but
    #: current Moonshot models reject anything other than 1 with a 400. The
    #: prompt does the constraining instead (JSON mode plus an explicit schema).
    #: Lower it only if you point KIMI_BASE_URL at an endpoint that allows it.
    kimi_temperature: float = 1.0
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
    def cors_origin_regex(self) -> str | None:
        """Matches any origin on a local network, on any port.

        Covers the ranges a machine on a home, office or VPN network actually
        answers on:

        * `10/8`, `172.16/12`, `192.168/16` — RFC 1918, ordinary LANs
        * `100.64/10` — CGNAT, which is what Tailscale hands out
        * `198.18/15` — RFC 2544 benchmarking, used by Cloudflare WARP,
          Zscaler and some VM NAT setups
        * `169.254/16` — link-local, when DHCP has not answered
        * `127.x` and `*.local` / `*.lan` / `*.home` / `*.internal` hostnames

        Deliberately not a general "allow anything": a routable public address
        never matches. `cors_allow_any_origin` is the escape hatch for a
        network none of this covers.
        """
        if not self.cors_allow_private_network:
            return None
        return (
            r"^https?://("
            r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
            r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
            r"|192\.168\.\d{1,3}\.\d{1,3}"
            r"|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}"
            r"|198\.(18|19)\.\d{1,3}\.\d{1,3}"
            r"|169\.254\.\d{1,3}\.\d{1,3}"
            r"|127\.\d{1,3}\.\d{1,3}\.\d{1,3}"
            r"|\[::1\]"
            r"|[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.(local|lan|home|internal)"
            r")(:\d+)?$"
        )

    @property
    def kimi_configured(self) -> bool:
        return bool(self.ai_enabled and self.kimi_api_key)

    @property
    def secret_key_is_ephemeral(self) -> bool:
        """True when the signing key cannot survive a restart.

        False when SECRET_KEY was configured explicitly, and also false when a
        generated key was successfully persisted to disk (see
        `_load_or_create_secret_key`). Only an unwritable data directory leaves
        it genuinely ephemeral.

        Stored IMAP passwords are encrypted with a key derived from it, so an
        ephemeral value means they cannot survive a restart.

        `model_fields_set` is the right test for "was it configured": it holds
        the fields actually supplied by the environment or `.env`, whereas
        `os.getenv` would miss anything read from the dotenv file.
        """
        if "secret_key" in self.model_fields_set:
            return False
        return not _secret_key_persisted

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


#: File holding the auto-generated signing key, so it survives restarts.
SECRET_KEY_FILE_NAME = ".secret_key"

#: Set by `get_settings` when a generated key was written to (or read from)
#: disk. Module-level rather than a field so it cannot be set from the
#: environment — it is an observation, not configuration.
_secret_key_persisted = False


def _load_or_create_secret_key(data_dir: Path) -> tuple[str, bool]:
    """Return a stable signing key, generating and storing one if needed.

    Without this, an unset SECRET_KEY means a fresh random key on every process
    start — so every restart, and every extra worker, silently invalidates
    tokens that were just issued, and the user is told their session expired
    seconds after signing in. Persisting the generated key makes the plain
    "just run it" path behave correctly with no configuration.

    Returns `(key, persisted)`. `persisted` is False only when the directory
    cannot be written, in which case the key really is per-process.
    """
    path = data_dir / SECRET_KEY_FILE_NAME
    try:
        if path.exists():
            existing = path.read_text(encoding="utf-8").strip()
            if existing:
                return existing, True

        generated = secrets.token_urlsafe(48)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(generated, encoding="utf-8")
        # Best effort; effectively a no-op on Windows.
        with contextlib.suppress(OSError):
            path.chmod(0o600)
        return generated, True
    except OSError:
        # Read-only or otherwise unwritable location: fall back to a
        # per-process key and let `secret_key_is_ephemeral` report it.
        return secrets.token_urlsafe(48), False


@lru_cache
def get_settings() -> Settings:
    global _secret_key_persisted

    settings = Settings()
    path = settings.sqlite_path
    data_dir = path.parent if path is not None else BACKEND_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    if "secret_key" not in settings.model_fields_set:
        key, persisted = _load_or_create_secret_key(data_dir)
        settings.secret_key = key
        _secret_key_persisted = persisted

    return settings


settings = get_settings()
