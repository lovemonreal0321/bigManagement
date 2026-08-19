"""Shared FastAPI dependencies: auth, workspace, and the global person filter."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import permissions
from app.core.database import get_db
from app.core.errors import AuthError
from app.core.security import decode_access_token
from app.models import Person, User, Workspace

DbSession = Annotated[Session, Depends(get_db)]


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("Authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()
    return None


def get_current_user(request: Request, db: DbSession) -> User:
    token = _extract_token(request)
    if not token:
        raise AuthError("Please sign in to continue.", code="missing_token")

    claims = decode_access_token(token)
    if not claims:
        raise AuthError("Your session expired. Please sign in again.", code="token_expired")

    user = db.get(User, claims.get("sub", ""))
    if user is None:
        raise AuthError("Your session is no longer valid.", code="unknown_user")
    if not user.is_active:
        # Disabling an account takes effect on the next request rather than
        # waiting for an unexpired token to lapse.
        raise AuthError(
            "That account has been disabled.", code="account_disabled"
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_admin_user(user: CurrentUser) -> User:
    """Guard for endpoints only an administrator may reach."""
    return permissions.require_admin(user)


AdminUser = Annotated[User, Depends(get_admin_user)]


def get_current_workspace(db: DbSession, user: CurrentUser) -> Workspace:
    workspace = db.get(Workspace, user.workspace_id)
    if workspace is None:  # pragma: no cover - bootstrap guarantees one exists
        raise AuthError("Workspace unavailable.", code="no_workspace")
    return workspace


CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]


class PersonScope:
    """Resolved global person filter (spec §4).

    Every list/aggregate endpoint takes this. Semantics:

    * `person_ids` omitted  -> all non-archived people ("everyone").
    * `person_ids` provided -> exactly those, in workspace sort order.
    * `include_archived`    -> archived people are eligible too, so historical
      views still work after someone is archived.

    Resolving ids here (rather than in each endpoint) means one place decides
    what "selected" means, and unknown ids are dropped rather than 404-ing a
    whole dashboard because one stale id sat in localStorage.
    """

    def __init__(self, people: list[Person], explicit: bool) -> None:
        self.people = people
        self.explicit = explicit
        self.ids = [p.id for p in people]
        self.by_id = {p.id: p for p in people}

    @property
    def is_empty(self) -> bool:
        return not self.ids

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PersonScope people={len(self.ids)} explicit={self.explicit}>"


def get_person_scope(
    db: DbSession,
    workspace: CurrentWorkspace,
    person_ids: Annotated[
        list[str] | None,
        Query(
            description=(
                "Selected people. Omit for everyone. Repeat the parameter for "
                "several: ?person_ids=a&person_ids=b"
            )
        ),
    ] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> PersonScope:
    stmt = select(Person).where(Person.workspace_id == workspace.id)
    if not include_archived:
        stmt = stmt.where(Person.archived_at.is_(None))
    stmt = stmt.order_by(Person.sort_order, Person.name)

    people = list(db.scalars(stmt))

    if person_ids:
        # Support both ?person_ids=a&person_ids=b and ?person_ids=a,b
        wanted: set[str] = set()
        for raw in person_ids:
            wanted.update(part.strip() for part in raw.split(",") if part.strip())
        people = [p for p in people if p.id in wanted]
        return PersonScope(people, explicit=True)

    return PersonScope(people, explicit=False)


SelectedPeople = Annotated[PersonScope, Depends(get_person_scope)]
