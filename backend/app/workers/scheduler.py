"""Background jobs: calendar sync and follow-up maintenance (spec §37).

An in-process APScheduler, not a separate worker service. The spec explicitly
asks for a modular monolith and warns against over-engineering; a personal
job-search tracker syncing a handful of calendars does not need a broker.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.core.config import settings
from app.core.database import session_scope
from app.core.timeutils import local_date, utcnow
from app.enums import ConnectionStatus, FollowUpStatus
from app.models import CalendarConnection, FollowUp, Person

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def sync_calendars_job() -> None:
    """Pull calendar changes for every healthy connection."""
    from app.domains.auth.service import get_workspace
    from app.domains.calendar import sync as sync_service

    db = session_scope()
    try:
        has_connections = db.scalar(
            select(CalendarConnection.id)
            .where(CalendarConnection.status != ConnectionStatus.DISCONNECTED.value)
            .limit(1)
        )
        if not has_connections:
            return  # nothing connected yet; stay quiet

        workspace = get_workspace(db)
        summary = sync_service.sync_all(db, workspace)
        logger.info(
            "scheduled calendar sync: %s events across %s connections (%s errors)",
            summary.total_events,
            len(summary.results),
            len(summary.errors),
        )
    except Exception:  # pragma: no cover - a failed job must not kill the app
        logger.exception("scheduled calendar sync failed")
    finally:
        db.close()


def followup_maintenance_job() -> None:
    """Wake snoozed follow-ups whose snooze has run out.

    Overdue/due-today are computed at read time, so this job only has the one
    piece of genuine state to fix: a `snoozed` row whose date has passed should
    go back to `open` so it reappears in the right bucket.
    """
    db = session_scope()
    try:
        now = utcnow()
        people = {p.id: p for p in db.scalars(select(Person))}
        woken = 0
        for follow_up in db.scalars(
            select(FollowUp).where(
                FollowUp.status == FollowUpStatus.SNOOZED.value,
                FollowUp.snoozed_until.is_not(None),
            )
        ):
            person = people.get(follow_up.person_id)
            today = local_date(now, person.timezone if person else None)
            if follow_up.snoozed_until is not None and follow_up.snoozed_until <= today:
                follow_up.status = FollowUpStatus.OPEN.value
                follow_up.snoozed_until = None
                woken += 1
        if woken:
            db.commit()
            logger.info("follow-up maintenance: %s snoozed items reopened", woken)
    except Exception:  # pragma: no cover
        logger.exception("follow-up maintenance failed")
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if not settings.enable_scheduler or settings.sync_interval_minutes <= 0:
        logger.info("background scheduler disabled by configuration")
        return None
    if _scheduler is not None:  # pragma: no cover - defensive
        return _scheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        sync_calendars_job,
        "interval",
        minutes=settings.sync_interval_minutes,
        id="calendar_sync",
        # Skip a run rather than piling them up if one takes a long time.
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        followup_maintenance_job,
        "interval",
        minutes=30,
        id="followup_maintenance",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "background scheduler started (calendar sync every %s minutes)",
        settings.sync_interval_minutes,
    )
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
