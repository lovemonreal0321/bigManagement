"""Who may change what.

One rule, applied everywhere:

* **admin** may do anything in the workspace.
* **user** may edit only the profiles assigned to them, and may read
  everything else.

Read access is deliberately unrestricted — the shared calendar, pipeline and
comparison analytics only mean something when everyone is visible. What is
restricted is *writing*.

Every write path funnels through `require_person_edit`, so adding a new
endpoint that forgets the check is a visible omission rather than a silent
hole.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import ForbiddenError, NotFoundError
from app.enums import UserRole
from app.models import (
    Application,
    CalendarEvent,
    FollowUp,
    InterviewEvent,
    InterviewStage,
    Person,
    User,
)


def is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN.value


def require_admin(user: User) -> User:
    if not is_admin(user):
        raise ForbiddenError(
            "Only an administrator can do that.", code="admin_required"
        )
    return user


def editable_person_ids(user: User) -> set[str] | None:
    """Profiles this user may edit. `None` means "all of them" (admin)."""
    if is_admin(user):
        return None
    return set(user.assigned_person_ids)


def can_edit_person(user: User, person_id: str | None) -> bool:
    if is_admin(user):
        return True
    if not person_id:
        return False
    return person_id in set(user.assigned_person_ids)


def require_person_edit(user: User, person_id: str | None, *, what: str = "that") -> None:
    """Raise unless the user may edit records belonging to this person."""
    if can_edit_person(user, person_id):
        return
    raise ForbiddenError(
        f"You can view {what}, but only an administrator or an assigned user "
        "can change it.",
        code="person_not_assigned",
    )


# --------------------------------------------------------------------------
# Convenience wrappers for the objects endpoints actually hold
# --------------------------------------------------------------------------


def require_application_edit(db: Session, user: User, application_id: str) -> Application:
    application = db.get(Application, application_id)
    if application is None:
        raise NotFoundError(
            "That application could not be found.", code="application_not_found"
        )
    require_person_edit(user, application.person_id, what="this application")
    return application


def require_stage_edit(db: Session, user: User, stage_id: str) -> InterviewStage:
    stage = db.get(InterviewStage, stage_id)
    if stage is None:
        raise NotFoundError(
            "That interview could not be found.", code="stage_not_found"
        )
    application = db.get(Application, stage.application_id)
    require_person_edit(
        user, application.person_id if application else None, what="this interview"
    )
    return stage


def require_event_edit(db: Session, user: User, event_id: str) -> InterviewEvent:
    """An interview event inherits its permission from the stage above it."""
    event = db.get(InterviewEvent, event_id)
    if event is None:
        raise NotFoundError(
            "That interview time could not be found.", code="event_not_found"
        )
    require_stage_edit(db, user, event.interview_stage_id)
    return event


def require_follow_up_edit(db: Session, user: User, follow_up_id: str) -> FollowUp:
    follow_up = db.get(FollowUp, follow_up_id)
    if follow_up is None:
        raise NotFoundError(
            "That follow-up could not be found.", code="follow_up_not_found"
        )
    require_person_edit(user, follow_up.person_id, what="this follow-up")
    return follow_up


def require_calendar_event_edit(db: Session, user: User, event_id: str) -> CalendarEvent:
    """Classifying, dismissing or linking a synced event edits that person's data."""
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise NotFoundError(
            "That calendar event could not be found.", code="event_not_found"
        )
    require_person_edit(user, event.person_id, what="this calendar event")
    return event


def require_person_exists(db: Session, person_id: str) -> Person:
    person = db.get(Person, person_id)
    if person is None:
        raise NotFoundError("That person could not be found.", code="person_not_found")
    return person
