"""Person management (spec §5)."""

from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.timeutils import utcnow
from app.domains.activity import service as activity_service
from app.domains.people.colors import derive_initials, next_available_color
from app.enums import ACTIVE_STATUSES, ActivityType, FollowUpStatus, InterviewStatus
from app.models import (
    Application,
    CalendarConnection,
    FollowUp,
    InterviewStage,
    Person,
    Workspace,
)
from app.schemas.person import PersonCreate, PersonUpdate


def list_people(
    db: Session, workspace: Workspace, *, include_archived: bool = False
) -> list[Person]:
    stmt = select(Person).where(Person.workspace_id == workspace.id)
    if not include_archived:
        stmt = stmt.where(Person.archived_at.is_(None))
    return list(db.scalars(stmt.order_by(Person.sort_order, Person.name)))


def get_person(db: Session, workspace: Workspace, person_id: str) -> Person:
    person = db.get(Person, person_id)
    if person is None or person.workspace_id != workspace.id:
        raise NotFoundError("That person could not be found.", code="person_not_found")
    return person


def create_person(db: Session, workspace: Workspace, payload: PersonCreate) -> Person:
    name = payload.name.strip()
    existing = db.scalars(
        select(Person).where(Person.workspace_id == workspace.id, Person.name == name)
    ).first()
    if existing is not None:
        raise ConflictError(
            f"There is already a person called {name}.", code="person_exists"
        )

    taken_colors = list(
        db.scalars(select(Person.color).where(Person.workspace_id == workspace.id))
    )
    max_order = (
        db.scalar(
            select(func.max(Person.sort_order)).where(
                Person.workspace_id == workspace.id
            )
        )
        or 0
    )

    person = Person(
        workspace_id=workspace.id,
        name=name,
        display_name=(payload.display_name or name).strip(),
        initials=(payload.initials or derive_initials(name)).upper()[:4],
        color=payload.color or next_available_color(taken_colors),
        avatar_url=payload.avatar_url,
        email=str(payload.email) if payload.email else None,
        timezone=payload.timezone or workspace.default_timezone or settings.default_timezone,
        sort_order=max_order + 1,
    )
    db.add(person)
    db.flush()

    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.PERSON_CREATED,
        message=f"{person.display_name} was added to the workspace",
        person_id=person.id,
    )
    db.commit()
    return person


def update_person(
    db: Session, workspace: Workspace, person_id: str, payload: PersonUpdate
) -> Person:
    person = get_person(db, workspace, person_id)
    data = payload.model_dump(exclude_unset=True)

    if data.get("name"):
        new_name = data["name"].strip()
        clash = db.scalars(
            select(Person).where(
                Person.workspace_id == workspace.id,
                Person.name == new_name,
                Person.id != person.id,
            )
        ).first()
        if clash is not None:
            raise ConflictError(
                f"There is already a person called {new_name}.", code="person_exists"
            )
        person.name = new_name

    if data.get("display_name"):
        person.display_name = data["display_name"].strip()
    if data.get("initials"):
        person.initials = data["initials"].upper()[:4]
    if data.get("color"):
        person.color = data["color"]
    if "avatar_url" in data:
        person.avatar_url = data["avatar_url"]
    if "email" in data:
        person.email = str(data["email"]) if data["email"] else None
    if data.get("timezone"):
        person.timezone = data["timezone"]
    if "sort_order" in data and data["sort_order"] is not None:
        person.sort_order = data["sort_order"]

    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.PERSON_UPDATED,
        message=f"{person.display_name}'s details were updated",
        person_id=person.id,
    )
    db.commit()
    return person


def archive_person(db: Session, workspace: Workspace, person_id: str) -> Person:
    """Archive rather than delete. History stays intact (spec §5)."""
    person = get_person(db, workspace, person_id)
    if person.archived_at is None:
        person.archived_at = utcnow()
        person.is_active = False
        activity_service.log(
            db,
            workspace_id=workspace.id,
            activity_type=ActivityType.PERSON_ARCHIVED,
            message=f"{person.display_name} was archived",
            person_id=person.id,
        )
        db.commit()
    return person


def restore_person(db: Session, workspace: Workspace, person_id: str) -> Person:
    person = get_person(db, workspace, person_id)
    if person.archived_at is not None:
        person.archived_at = None
        person.is_active = True
        activity_service.log(
            db,
            workspace_id=workspace.id,
            activity_type=ActivityType.PERSON_RESTORED,
            message=f"{person.display_name} was restored",
            person_id=person.id,
        )
        db.commit()
    return person


def check_deletable(db: Session, workspace: Workspace, person_id: str) -> tuple[bool, int]:
    """A person with application history can never be hard-deleted (spec §5)."""
    person = get_person(db, workspace, person_id)
    count = (
        db.scalar(
            select(func.count(Application.id)).where(Application.person_id == person.id)
        )
        or 0
    )
    return count == 0, count


def delete_person(db: Session, workspace: Workspace, person_id: str) -> None:
    person = get_person(db, workspace, person_id)
    deletable, count = check_deletable(db, workspace, person_id)
    if not deletable:
        raise ValidationError(
            (
                f"{person.display_name} has {count} application"
                f"{'s' if count != 1 else ''} on record and cannot be deleted. "
                "Archive them instead — their history stays available."
            ),
            code="person_has_history",
            details={"application_count": count},
        )
    db.delete(person)
    db.commit()


def get_people_stats(
    db: Session, workspace: Workspace, people: list[Person]
) -> dict[str, dict[str, int]]:
    """Per-person counters for the People page.

    Four grouped aggregate queries rather than four per person (spec §56).
    """
    ids = [p.id for p in people]
    stats: dict[str, dict[str, int]] = {
        pid: {
            "application_count": 0,
            "active_application_count": 0,
            "upcoming_interview_count": 0,
            "open_follow_up_count": 0,
            "calendar_connection_count": 0,
        }
        for pid in ids
    }
    if not ids:
        return stats

    for person_id, total, active in db.execute(
        select(
            Application.person_id,
            func.count(Application.id),
            func.sum(
                case(
                    (
                        Application.status.in_([s.value for s in ACTIVE_STATUSES]),
                        1,
                    ),
                    else_=0,
                )
            ),
        )
        .where(Application.person_id.in_(ids), Application.archived_at.is_(None))
        .group_by(Application.person_id)
    ):
        stats[person_id]["application_count"] = int(total or 0)
        stats[person_id]["active_application_count"] = int(active or 0)

    now = utcnow()
    for person_id, count in db.execute(
        select(Application.person_id, func.count(InterviewStage.id))
        .join(Application, Application.id == InterviewStage.application_id)
        .where(
            Application.person_id.in_(ids),
            InterviewStage.status == InterviewStatus.SCHEDULED.value,
            InterviewStage.scheduled_start >= now,
        )
        .group_by(Application.person_id)
    ):
        stats[person_id]["upcoming_interview_count"] = int(count or 0)

    for person_id, count in db.execute(
        select(FollowUp.person_id, func.count(FollowUp.id))
        .where(
            FollowUp.person_id.in_(ids),
            FollowUp.status.in_([FollowUpStatus.OPEN.value, FollowUpStatus.SNOOZED.value]),
        )
        .group_by(FollowUp.person_id)
    ):
        stats[person_id]["open_follow_up_count"] = int(count or 0)

    for person_id, count in db.execute(
        select(CalendarConnection.person_id, func.count(CalendarConnection.id))
        .where(CalendarConnection.person_id.in_(ids))
        .group_by(CalendarConnection.person_id)
    ):
        stats[person_id]["calendar_connection_count"] = int(count or 0)

    return stats
