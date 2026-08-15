"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser, DbSession
from app.core.security import create_access_token
from app.domains.auth import service as auth_service
from app.schemas.auth import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = auth_service.authenticate(db, payload.username, payload.password)
    token, expires_in = create_access_token(
        user.id, extra_claims={"username": user.username}
    )
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/logout")
def logout(user: CurrentUser) -> dict[str, bool]:
    """Client-side token disposal.

    Tokens are stateless and short-lived; there is no server-side session to
    destroy. The endpoint exists so the frontend has one obvious thing to call.
    """
    return {"ok": True}
