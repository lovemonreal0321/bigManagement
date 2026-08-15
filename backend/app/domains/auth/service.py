"""Authentication and workspace bootstrap.

The deployment has one fixed account whose credentials come from settings
(`ADMIN_USERNAME` / `ADMIN_PASSWORD`). `ensure_bootstrap` is idempotent and
runs on startup, so changing the password in `.env` and restarting takes
effect immediately rather than requiring a manual user-management flow.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AuthError
from app.core.security import hash_password, verify_password
from app.core.timeutils import utcnow
from app.enums import (
    BUILTIN_INTERVIEW_TYPES,
    FINAL_ROUND_TYPES,
    INTERVIEW_TYPE_SHORT_LABELS,
    SCREENING_TYPES,
    TECHNICAL_TYPES,
)
from app.models import InterviewType, User, Workspace

logger = logging.getLogger(__name__)


def get_workspace(db: Session) -> Workspace:
    """The single workspace, created on demand."""
    workspace = db.scalars(select(Workspace).limit(1)).first()
    if workspace is None:
        workspace = Workspace(
            name=settings.workspace_name,
            default_timezone=settings.default_timezone,
            sync_window_past_days=settings.sync_window_past_days,
            sync_window_future_days=settings.sync_window_future_days,
            followup_after_interview_business_days=(
                settings.followup_after_interview_business_days
            ),
            followup_chain_business_days=settings.followup_chain_business_days,
            waiting_for_feedback_threshold_days=(
                settings.waiting_for_feedback_threshold_days
            ),
            no_activity_ghosted_threshold_days=(
                settings.no_activity_ghosted_threshold_days
            ),
        )
        db.add(workspace)
        db.flush()
    return workspace


def ensure_builtin_interview_types(db: Session, workspace: Workspace) -> None:
    """Insert any missing built-in interview types (spec §14)."""
    existing = {
        key
        for key in db.scalars(
            select(InterviewType.key).where(
                InterviewType.workspace_id == workspace.id,
                InterviewType.is_builtin.is_(True),
            )
        )
    }
    for order, (key, label) in enumerate(BUILTIN_INTERVIEW_TYPES):
        if key in existing:
            continue
        db.add(
            InterviewType(
                workspace_id=workspace.id,
                key=key,
                label=label,
                short_label=INTERVIEW_TYPE_SHORT_LABELS.get(key, label),
                is_builtin=True,
                sort_order=order,
                counts_as_technical=key in TECHNICAL_TYPES,
                counts_as_final=key in FINAL_ROUND_TYPES,
                counts_as_screening=key in SCREENING_TYPES,
            )
        )


def ensure_admin_user(db: Session, workspace: Workspace) -> User:
    """Create or re-sync the fixed admin account from settings."""
    user = db.scalars(
        select(User).where(User.username == settings.admin_username)
    ).first()

    if user is None:
        # A username change in .env should not orphan the old account into a
        # second unusable login, so reuse the sole existing user if there is one.
        user = db.scalars(select(User).limit(1)).first()
        if user is not None:
            user.username = settings.admin_username
        else:
            user = User(
                workspace_id=workspace.id,
                username=settings.admin_username,
                display_name="Admin",
                password_hash=hash_password(settings.admin_password),
            )
            db.add(user)
            db.flush()
            return user

    # Keep the stored hash in step with the configured password.
    if not verify_password(settings.admin_password, user.password_hash):
        user.password_hash = hash_password(settings.admin_password)
        logger.info("admin password re-synced from configuration")
    user.workspace_id = workspace.id
    return user


def ensure_bootstrap(db: Session) -> tuple[Workspace, User]:
    """Idempotent startup bootstrap: workspace + interview types + admin."""
    workspace = get_workspace(db)
    ensure_builtin_interview_types(db, workspace)
    user = ensure_admin_user(db, workspace)
    db.commit()
    return workspace, user


def authenticate(db: Session, username: str, password: str) -> User:
    user = db.scalars(select(User).where(User.username == username)).first()
    # Hash a dummy password when the user does not exist so a wrong username
    # and a wrong password take a similar amount of time.
    if user is None:
        verify_password(password, hash_password("placeholder"))
        raise AuthError("Incorrect username or password.", code="invalid_credentials")
    if not verify_password(password, user.password_hash):
        raise AuthError("Incorrect username or password.", code="invalid_credentials")

    user.last_login_at = utcnow()
    db.commit()
    return user
