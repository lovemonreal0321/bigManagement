"""Authentication, the signed-in user, and user administration."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.core.deps import AdminUser, CurrentUser, CurrentWorkspace, DbSession
from app.core.security import create_access_token
from app.domains.auth import service as auth_service
from app.models import User
from app.schemas.auth import (
    AssignPeopleRequest,
    ChangePasswordRequest,
    LoginRequest,
    SetPasswordRequest,
    TokenResponse,
    UserCreate,
    UserOut,
    UserUpdate,
)

router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])


def _to_out(user: User) -> UserOut:
    """`assigned_person_ids` is a model property, which `from_attributes` reads."""
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = auth_service.authenticate(db, payload.username, payload.password)
    token, expires_in = create_access_token(
        user.id, extra_claims={"username": user.username, "role": user.role}
    )
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=_to_out(user),
    )


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return _to_out(user)


@router.post("/password", response_model=UserOut)
def change_password(
    payload: ChangePasswordRequest, user: CurrentUser, db: DbSession
) -> UserOut:
    """Change your own password."""
    updated = auth_service.change_own_password(
        db,
        user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return _to_out(updated)


@router.post("/logout")
def logout(user: CurrentUser) -> dict[str, bool]:
    """Client-side token disposal.

    Tokens are stateless and short-lived; there is no server-side session to
    destroy. The endpoint exists so the frontend has one obvious thing to call.
    """
    return {"ok": True}


# --------------------------------------------------------------------------
# User administration — every route below is admin-only via `AdminUser`
# --------------------------------------------------------------------------


@users_router.get("", response_model=list[UserOut])
def list_users(
    admin: AdminUser, workspace: CurrentWorkspace, db: DbSession
) -> list[UserOut]:
    return [_to_out(user) for user in auth_service.list_users(db, workspace)]


@users_router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate, admin: AdminUser, workspace: CurrentWorkspace, db: DbSession
) -> UserOut:
    user = auth_service.create_user(
        db,
        workspace,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        role=payload.role.value,
        email=payload.email,
        person_ids=payload.person_ids,
    )
    return _to_out(user)


@users_router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: str, admin: AdminUser, workspace: CurrentWorkspace, db: DbSession
) -> UserOut:
    return _to_out(auth_service.get_user(db, workspace, user_id))


@users_router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    payload: UserUpdate,
    admin: AdminUser,
    workspace: CurrentWorkspace,
    db: DbSession,
) -> UserOut:
    user = auth_service.update_user(
        db,
        workspace,
        user_id,
        acting_user=admin,
        display_name=payload.display_name,
        email=payload.email,
        role=payload.role.value if payload.role else None,
        is_active=payload.is_active,
    )
    return _to_out(user)


@users_router.put("/{user_id}/password", response_model=UserOut)
def set_user_password(
    user_id: str,
    payload: SetPasswordRequest,
    admin: AdminUser,
    workspace: CurrentWorkspace,
    db: DbSession,
) -> UserOut:
    user = auth_service.set_user_password(db, workspace, user_id, payload.password)
    return _to_out(user)


@users_router.put("/{user_id}/people", response_model=UserOut)
def assign_people(
    user_id: str,
    payload: AssignPeopleRequest,
    admin: AdminUser,
    workspace: CurrentWorkspace,
    db: DbSession,
) -> UserOut:
    """Replace the set of profiles this user may edit."""
    user = auth_service.get_user(db, workspace, user_id)
    auth_service.set_assigned_people(db, workspace, user, payload.person_ids)
    return _to_out(user)


@users_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str, admin: AdminUser, workspace: CurrentWorkspace, db: DbSession
) -> None:
    auth_service.delete_user(db, workspace, user_id, acting_user=admin)
