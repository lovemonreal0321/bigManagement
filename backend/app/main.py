"""FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import BACKEND_DIR, settings
from app.core.database import session_scope
from app.core.errors import CatchUnhandledMiddleware, register_exception_handlers
from app.workers.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run_migrations() -> None:
    """Bring the database up to head.

    Local-first product: the app should work after `uvicorn app.main:app` with
    no separate migration step. Alembic is still the source of truth, and
    AUTO_MIGRATE=false turns this off for anyone who wants manual control.
    """
    from alembic.config import Config

    from alembic import command

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if settings.auto_migrate:
        try:
            run_migrations()
            logger.info("database migrations are up to date")
        except Exception:
            logger.exception("could not apply migrations automatically")

    db = session_scope()
    try:
        from app.domains.auth.service import ensure_bootstrap

        workspace, user = ensure_bootstrap(db)
        logger.info(
            "workspace %r ready; sign in as %r", workspace.name, user.username
        )
    finally:
        db.close()

    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Job Search Command Center — applications, interviews, follow-ups, "
        "calendar sync and analytics for a shared workspace of job seekers."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# Added before CORS so it ends up *inside* it. An unhandled error then still
# comes back with CORS headers, showing its real status in the browser instead
# of a misleading "blocked by CORS policy".
app.add_middleware(CatchUnhandledMiddleware)

if settings.cors_allow_any_origin:
    logger.warning(
        "CORS_ALLOW_ANY_ORIGIN is on — every origin is accepted. "
        "Only appropriate on a network you control."
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=".*",
        # Credentials cannot be combined with a reflected wildcard origin, and
        # they are not needed: the session is a bearer token, not a cookie.
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        # Teammates on the same LAN or VPN, whose address may change at any
        # time. See `Settings.cors_origin_regex`.
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

register_exception_handlers(app)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health", tags=["health"])
def health() -> dict[str, object]:
    from app.domains.calendar.providers import available_providers

    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "providers": {
            adapter.key: adapter.is_configured for adapter in available_providers()
        },
    }


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "api": settings.api_prefix,
    }
