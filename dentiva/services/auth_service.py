"""Authentication, user creation, and password management service."""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from dentiva.auth.password import DEFAULT_ROUNDS, hash_password, needs_rehash, verify_password
from dentiva.core.errors import AuthenticationError, ValidationError
from dentiva.core.permissions import Permission, Principal
from dentiva.models import Role, User

from .audit_service import record as audit_record

log = logging.getLogger(__name__)


DEFAULT_LOCKOUT_MINUTES = 10
MAX_FAILED_ATTEMPTS = 5


def _build_principal(user: User) -> Principal:
    return Principal(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name or user.username,
        permissions=list(user.permissions_list()),
        is_superuser=bool(user.is_superuser),
    )


def _create_initial_admin(session: Session, username: str, password: str, display_name: str) -> User:
    """Create the first Administrator user. Only called during first-run setup."""
    admin_role = session.scalar(select(Role).where(Role.name == "Administrator"))
    user = User(
        username=username.lower(),
        password_hash=hash_password(password, rounds=DEFAULT_ROUNDS),
        display_name=display_name or username,
        role_id=admin_role.id if admin_role else None,
        is_superuser=True,
        is_active=True,
        password_set_at=dt.datetime.utcnow(),
        failed_login_attempts=0,
    )
    session.add(user)
    session.flush()
    audit_record(
        session, None, "user.create_initial_admin",
        entity_type="user", entity_id=user.id,
        summary=f"Initial administrator '{username}' created during setup.",
    )
    return user


def authenticate(session: Session, username: str, password: str,
                 *, max_attempts: int = MAX_FAILED_ATTEMPTS,
                 lockout_minutes: int = DEFAULT_LOCKOUT_MINUTES) -> Principal:
    """Authenticate a user and return a Principal.

    Applies failed-attempt tracking and temporary lockout suitable for an
    offline desktop application (online brute force is not possible; the
    goal is to discourage casual shoulder attempts).
    """
    username_norm = (username or "").strip().lower()
    if not username_norm or not password:
        raise AuthenticationError("Username and password are required.")

    user = session.scalar(select(User).where(User.username == username_norm))
    if user is None or not user.is_active:
        # To avoid username enumeration we raise the same message.
        raise AuthenticationError("Invalid username or password.")

    # Check lockout
    if user.locked_until and user.locked_until > dt.datetime.utcnow():
        mins = int((user.locked_until - dt.datetime.utcnow()).total_seconds() // 60) + 1
        raise AuthenticationError(
            f"Account is temporarily locked. Try again in {mins} minute(s)."
        )
    if user.locked_until and user.locked_until <= dt.datetime.utcnow():
        user.locked_until = None
        user.failed_login_attempts = 0

    if not verify_password(password, user.password_hash):
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= max_attempts:
            user.locked_until = dt.datetime.utcnow() + dt.timedelta(minutes=lockout_minutes)
            audit_record(session, None, "user.lockout", entity_type="user", entity_id=user.id,
                         summary=f"Account locked after {max_attempts} failed attempts.")
        session.flush()
        raise AuthenticationError("Invalid username or password.")

    # Successful login.
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = dt.datetime.utcnow()
    # Transparent password upgrade if work factor changed.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        user.password_set_at = dt.datetime.utcnow()
    session.flush()

    principal = _build_principal(user)
    audit_record(session, principal, "auth.login", entity_type="user", entity_id=user.id,
                 summary=f"User '{username_norm}' logged in.")
    return principal


def change_password(session: Session, principal: Principal, user_id: int,
                    current_password: str, new_password: str) -> None:
    """Change a user's password. Non-admins can only change their own."""
    target = session.get(User, user_id)
    if target is None:
        from dentiva.core.errors import NotFoundError
        raise NotFoundError("User", user_id)
    if target.id != principal.user_id and not principal.has(Permission.USERS_RESET_PASSWORD):
        from dentiva.core.errors import PermissionDeniedError
        raise PermissionDeniedError(permission=Permission.USERS_RESET_PASSWORD.value)
    if target.id == principal.user_id:
        if not verify_password(current_password or "", target.password_hash):
            raise ValidationError("Current password is incorrect.", field="current_password")
    if not new_password or len(new_password) < 6:
        raise ValidationError("New password must be at least 6 characters.", field="new_password")
    target.password_hash = hash_password(new_password)
    target.password_set_at = dt.datetime.utcnow()
    target.must_change_password = False
    session.flush()
    audit_record(session, principal, "user.change_password", entity_type="user",
                 entity_id=target.id, summary="Password changed.")


def create_user(session: Session, principal: Principal, *, username: str,
                password: str, display_name: str, role_id: int | None,
                staff_id: int | None = None, is_superuser: bool = False) -> User:
    from dentiva.core.errors import PermissionDeniedError
    if not principal.has(Permission.USERS_CREATE):
        raise PermissionDeniedError(permission=Permission.USERS_CREATE.value)
    uname = (username or "").strip().lower()
    if len(uname) < 3:
        raise ValidationError("Username must be at least 3 characters.", field="username")
    if not password or len(password) < 6:
        raise ValidationError("Password must be at least 6 characters.", field="password")
    existing = session.scalar(select(User).where(User.username == uname))
    if existing:
        raise ValidationError("That username is already in use.", field="username")
    user = User(
        username=uname,
        password_hash=hash_password(password),
        display_name=display_name or uname,
        role_id=role_id,
        staff_id=staff_id,
        is_superuser=bool(is_superuser),
        is_active=True,
        password_set_at=dt.datetime.utcnow(),
    )
    session.add(user)
    session.flush()
    audit_record(session, principal, "user.create", entity_type="user", entity_id=user.id,
                 summary=f"User '{uname}' created.")
    return user
