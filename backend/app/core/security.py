"""Password hashing and JWT issuing/verification."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from app.core.timeutils import utcnow


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash in the DB — treat as a failed login, never a 500.
        return False


def create_access_token(
    subject: str, extra_claims: dict[str, Any] | None = None
) -> tuple[str, int]:
    """Return `(token, expires_in_seconds)`."""
    expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    now = utcnow()
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, int(expires_delta.total_seconds())


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode a token, returning None if it is invalid or expired."""
    try:
        return jwt.decode(
            token, settings.secret_key, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return None


def create_state_token(payload: dict[str, Any], ttl_minutes: int = 15) -> str:
    """Short-lived signed token used as the OAuth `state` parameter.

    Signing the state means the callback can trust which person the flow was
    started for without keeping server-side session state.
    """
    now = utcnow()
    claims = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
        "purpose": "oauth_state",
    }
    return jwt.encode(claims, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_state_token(token: str) -> dict[str, Any] | None:
    claims = decode_access_token(token)
    if not claims or claims.get("purpose") != "oauth_state":
        return None
    return claims
