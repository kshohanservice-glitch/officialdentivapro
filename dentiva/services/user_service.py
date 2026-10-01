"""User management service (CRUD, role assignment, listing)."""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from dentiva.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from dentiva.core.permissions import Permission, Principal
from dentiva.models import Role, User

from .audit_service import record as audit_record
from .auth_service import hash_password

log = logging.getLogger(__name__)


def list_users(session: Session, principal: Principal) -> list[User]:
    if not principal.has(Permission.USERS_VIEW):
        raise PermissionDeniedError(permission=Permission.USERS_VIEW.value)
    return list(session.scalars(select(User).order_by(User.username)))


def get_user(session: Session, user_id: int) -> User:
    u = session.get(User, user_id)
    if u is None:
        raise NotFoundError("User", user_id)
    return u


def list_roles(session: Session, principal: Principal) -> list[Role]:
    if not principal.has(Permission.ROLES_MANAGE) and not principal.has(Permission.USERS_VIEW):
        raise PermissionDeniedError(permission=Permission.USERS_VIEW.value)
    return list(session.scalars(select(Role).order_by(Role.name)))


def set_user_role(session: Session, principal: Principal, user_id: int, role_id: Optional[int]) -> User:
    if not principal.has(Permission.ROLES_MANAGE):
        raise PermissionDeniedError(permission=Permission.ROLES_MANAGE.value)
    u = get_user(session, user_id)
    if role_id is not None:
        role = session.get(Role, role_id)
        if role is None:
            raise ValidationError("Selected role does not exist.", field="role_id")
    u.role_id = role_id
    # Superuser flag is preserved for the initial admin; setting role does
    # not grant or revoke it (separate control).
    session.flush()
    audit_record(session, principal, "user.role_change", entity_type="user", entity_id=u.id,
                 summary=f"Role updated to role_id={role_id}.")
    return u


def deactivate_user(session: Session, principal: Principal, user_id: int) -> User:
    if not principal.has(Permission.USERS_EDIT):
        raise PermissionDeniedError(permission=Permission.USERS_EDIT.value)
    u = get_user(session, user_id)
    if u.id == principal.user_id:
        raise ValidationError("You cannot deactivate your own account.")
    u.is_active = False
    session.flush()
    audit_record(session, principal, "user.deactivate", entity_type="user", entity_id=u.id,
                 summary="User deactivated.")
    return u


def reset_password(session: Session, principal: Principal, user_id: int, new_password: str) -> None:
    if not principal.has(Permission.USERS_RESET_PASSWORD):
        raise PermissionDeniedError(permission=Permission.USERS_RESET_PASSWORD.value)
    u = get_user(session, user_id)
    if len(new_password or "") < 6:
        raise ValidationError("Password must be at least 6 characters.", field="new_password")
    u.password_hash = hash_password(new_password)
    u.must_change_password = True
    u.failed_login_attempts = 0
    u.locked_until = None
    session.flush()
    audit_record(session, principal, "user.reset_password", entity_type="user", entity_id=u.id,
                 summary="Password reset by administrator.")
