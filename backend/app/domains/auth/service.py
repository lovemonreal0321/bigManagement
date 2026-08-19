"""Authentication, roles and user management.

Two rules worth stating up front:

* `ADMIN_PASSWORD` in `.env` only *seeds* the first admin. It never overwrites
  an existing account, because an admin who changes their password in the UI
  would otherwise find it silently reverted on the next restart.
* The super password is a deliberate recovery path: it always authenticates an
  **admin** account, whatever that admin's own password is. Every use is
  written to the activity log, so it is auditable rather than invisible.
"""

from __future__ import annotations

import logging
import secrets

import bcrypt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    AuthError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.security import hash_password, verify_password
from app.core.timeutils import utcnow
from app.enums import (
    BUILTIN_INTERVIEW_TYPES,
    FINAL_ROUND_TYPES,
    INTERVIEW_TYPE_SHORT_LABELS,
    SCREENING_TYPES,
    TECHNICAL_TYPES,
    ActivityType,
    UserRole,
)
from app.models import InterviewType, Person, User, Workspace

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 6


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
    """Insert any missing built-in interview types."""
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
    """Make sure exactly one admin exists, without clobbering a changed password."""
    user = db.scalars(
        select(User).where(User.username == settings.admin_username)
    ).first()

    if user is None:
        # Adopt a pre-existing sole account rather than creating a second,
        # unusable login when ADMIN_USERNAME changes.
        user = db.scalars(select(User).limit(1)).first()
        if user is not None:
            user.username = settings.admin_username
        else:
            user = User(
                workspace_id=workspace.id,
                username=settings.admin_username,
                display_name="Admin",
                password_hash=hash_password(settings.admin_password),
                role=UserRole.ADMIN.value,
            )
            db.add(user)
            db.flush()
            logger.info("created initial admin account %r", user.username)
            return user

    # An existing account keeps its password. `.env` seeds, it does not enforce.
    user.workspace_id = workspace.id
    user.role = UserRole.ADMIN.value
    user.is_active = True
    return user


def ensure_bootstrap(db: Session) -> tuple[Workspace, User]:
    """Idempotent startup bootstrap: workspace + interview types + admin."""
    workspace = get_workspace(db)
    ensure_builtin_interview_types(db, workspace)
    user = ensure_admin_user(db, workspace)
    db.commit()
    return workspace, user


# --------------------------------------------------------------------------
# Sign in
# --------------------------------------------------------------------------


def _super_password_matches(candidate: str) -> bool:
    """Whether `candidate` is the configured recovery password."""
    if not settings.super_password_enabled:
        return False

    # A plaintext override in `.env` wins over the shipped hash.
    if settings.super_password:
        return secrets.compare_digest(candidate, settings.super_password)

    if not settings.super_password_hash:
        return False
    try:
        return bcrypt.checkpw(
            candidate.encode("utf-8"), settings.super_password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):  # pragma: no cover - malformed hash
        return False


def authenticate(db: Session, username: str, password: str) -> User:
    """Verify credentials, honouring the admin recovery password."""
    from app.domains.activity import service as activity_service

    user = db.scalars(select(User).where(User.username == username)).first()
    if user is None:
        # Spend similar time on an unknown username as on a wrong password.
        verify_password(password, hash_password("placeholder"))
        raise AuthError("Incorrect username or password.", code="invalid_credentials")

    if not user.is_active:
        raise AuthError(
            "That account has been disabled. Ask an administrator to re-enable it.",
            code="account_disabled",
        )

    used_super = False
    if verify_password(password, user.password_hash):
        pass
    elif user.is_admin and _super_password_matches(password):
        # The recovery path: only ever for an admin, and never silent.
        used_super = True
        logger.warning("recovery password used for admin %r", user.username)
    else:
        raise AuthError("Incorrect username or password.", code="invalid_credentials")

    user.last_login_at = utcnow()

    if used_super:
        activity_service.log(
            db,
            workspace_id=user.workspace_id,
            activity_type=ActivityType.SECURITY_EVENT,
            message=f"{user.username} signed in with the recovery password",
            meta={"recovery_login": True},
        )

    db.commit()
    return user


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------


def _validate_password(password: str) -> str:
    password = password.strip()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"Choose a password of at least {MIN_PASSWORD_LENGTH} characters.",
            code="password_too_short",
        )
    return password


def change_own_password(
    db: Session, user: User, *, current_password: str, new_password: str
) -> User:
    """Change your own password.

    The recovery password is accepted as `current_password` for an admin, so an
    admin who has forgotten their own password can set a new one after signing
    in with it.
    """
    valid = verify_password(current_password, user.password_hash) or (
        user.is_admin and _super_password_matches(current_password)
    )
    if not valid:
        raise AuthError(
            "That current password is not correct.", code="invalid_credentials"
        )

    user.password_hash = hash_password(_validate_password(new_password))
    user.must_change_password = False
    user.password_changed_at = utcnow()
    db.commit()
    return user


# --------------------------------------------------------------------------
# User management (admin only — callers enforce this)
# --------------------------------------------------------------------------


def list_users(db: Session, workspace: Workspace) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .where(User.workspace_id == workspace.id)
            .order_by(User.role, User.username)
        )
    )


def get_user(db: Session, workspace: Workspace, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None or user.workspace_id != workspace.id:
        raise NotFoundError("That user could not be found.", code="user_not_found")
    return user


def create_user(
    db: Session,
    workspace: Workspace,
    *,
    username: str,
    password: str,
    display_name: str | None = None,
    role: str = UserRole.USER.value,
    email: str | None = None,
    person_ids: list[str] | None = None,
) -> User:
    username = username.strip().lower()
    if not username:
        raise ValidationError("Choose a username.", code="username_required")

    existing = db.scalars(select(User).where(User.username == username)).first()
    if existing is not None:
        raise ConflictError(
            f"The username {username} is already taken.", code="username_taken"
        )

    user = User(
        workspace_id=workspace.id,
        username=username,
        display_name=(display_name or username).strip(),
        email=email,
        password_hash=hash_password(_validate_password(password)),
        role=role,
        # An admin-chosen password should be replaced by one only the user
        # knows, so the UI can prompt on first sign-in.
        must_change_password=True,
    )
    db.add(user)
    db.flush()
    set_assigned_people(db, workspace, user, person_ids or [], commit=False)
    db.commit()
    return user


def update_user(
    db: Session,
    workspace: Workspace,
    user_id: str,
    *,
    acting_user: User,
    display_name: str | None = None,
    email: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> User:
    user = get_user(db, workspace, user_id)

    if display_name is not None:
        user.display_name = display_name.strip() or user.username
    if email is not None:
        user.email = email or None

    if role is not None and role != user.role:
        _guard_last_admin(db, workspace, user, new_role=role)
        user.role = role
    if is_active is not None and is_active != user.is_active:
        if not is_active:
            if user.id == acting_user.id:
                raise ValidationError(
                    "You cannot disable your own account.", code="cannot_disable_self"
                )
            _guard_last_admin(db, workspace, user, deactivating=True)
        user.is_active = is_active

    db.commit()
    return user


def set_user_password(
    db: Session, workspace: Workspace, user_id: str, password: str
) -> User:
    """Admin sets someone's password."""
    user = get_user(db, workspace, user_id)
    user.password_hash = hash_password(_validate_password(password))
    user.must_change_password = True
    db.commit()
    return user


def set_assigned_people(
    db: Session,
    workspace: Workspace,
    user: User,
    person_ids: list[str],
    *,
    commit: bool = True,
) -> User:
    """Replace the set of profiles this user may edit."""
    wanted = set(person_ids)
    people = (
        list(
            db.scalars(
                select(Person).where(
                    Person.workspace_id == workspace.id, Person.id.in_(wanted)
                )
            )
        )
        if wanted
        else []
    )
    missing = wanted - {person.id for person in people}
    if missing:
        raise ValidationError(
            "Some of those profiles do not exist.",
            code="unknown_person",
            details={"unknown_ids": sorted(missing)},
        )

    user.people = people
    if commit:
        db.commit()
    return user


def delete_user(
    db: Session, workspace: Workspace, user_id: str, *, acting_user: User
) -> None:
    user = get_user(db, workspace, user_id)
    if user.id == acting_user.id:
        raise ValidationError(
            "You cannot delete your own account.", code="cannot_delete_self"
        )
    _guard_last_admin(db, workspace, user, deleting=True)
    db.delete(user)
    db.commit()


def _guard_last_admin(
    db: Session,
    workspace: Workspace,
    user: User,
    *,
    new_role: str | None = None,
    deactivating: bool = False,
    deleting: bool = False,
) -> None:
    """Refuse changes that would leave the workspace with no active admin."""
    if not user.is_admin:
        return
    if new_role == UserRole.ADMIN.value:
        return

    other_admins = (
        db.scalar(
            select(func.count(User.id)).where(
                User.workspace_id == workspace.id,
                User.role == UserRole.ADMIN.value,
                User.is_active.is_(True),
                User.id != user.id,
            )
        )
        or 0
    )
    if other_admins == 0:
        action = (
            "delete" if deleting else "disable" if deactivating else "change the role of"
        )
        raise ForbiddenError(
            f"You cannot {action} the only administrator. Promote another user first.",
            code="last_admin",
        )
