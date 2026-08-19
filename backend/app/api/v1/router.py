"""API v1 router assembly."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import (
    analytics,
    applications,
    auth,
    calendar,
    dashboard,
    email,
    followups,
    interviews,
    people,
    settings,
)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(auth.users_router)
api_router.include_router(people.router)
api_router.include_router(applications.router)
api_router.include_router(interviews.types_router)
api_router.include_router(interviews.router)
api_router.include_router(followups.router)
api_router.include_router(calendar.router)
api_router.include_router(email.router)
api_router.include_router(email.ai_router)
api_router.include_router(analytics.router)
api_router.include_router(dashboard.router)
api_router.include_router(settings.router)
