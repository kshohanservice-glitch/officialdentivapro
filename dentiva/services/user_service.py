# mypy: disable-error-code="arg-type, union-attr, assignment"
"""User management service (CRUD, role assignment, listing, role permissions)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dentiva.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from dentiva.core.permissions import Permission, Principal
from dentiva.models import PermissionAssignment, Role, User

from .audit_service import record as audit_record
from .auth_service import hash_password

log = logging.getLogger(__name__)


@dataclass
class UserRow:
    id: int
    username: str
    display_name: str
    role_id: int | None
    role_name: str
    is_active: bool
    is_superuser: bool
    last_login_at: object
    must_change_password: bool


@dataclass
class RoleRow:
    id: int
    name: str
    description: str
    is_system: bool
    permissions: list[str]


def _row_from(u: User, roles_map: dict[int, Role]) -> UserRow:
    role = roles_map.get(u.role_id) if u.role_id else None
    return UserRow(
        id=u.id, username=u.username, display_name=u.display_name or "",
        role_id=u.role_id, role_name=role.name if role else "—",
        is_active=bool(u.is_active), is_superuser=bool(u.is_superuser),
        last_login_at=u.last_login_at, must_change_password=bool(u.must_change_password),
    )


def list_users(session: Session, principal: Principal) -> list[UserRow]:
    if not principal.has(Permission.USERS_VIEW):
        raise PermissionDeniedError(permission=Permission.USERS_VIEW.value)
    users = list(session.scalars(select(User).order_by(User.username)))
    roles = {r.id: r for r in session.scalars(select(Role))}
    return [_row_from(u, roles) for u in users]


def get_user(session: Session, user_id: int) -> User:
    u = session.get(User, user_id)
    if u is None:
        raise NotFoundError("User", user_id)
    return u


def list_roles(session: Session, principal: Principal) -> list[RoleRow]:
    if not principal.has(Permission.ROLES_MANAGE) and not principal.has(Permission.USERS_VIEW):
        raise PermissionDeniedError(permission=Permission.USERS_VIEW.value)
    roles = list(session.scalars(select(Role).order_by(Role.name)))
    perms_by_role: dict[int, list[str]] = {r.id: [] for r in roles}
    for pa in session.scalars(select(PermissionAssignment)):
        perms_by_role.setdefault(pa.role_id, []).append(pa.permission)
    out: list[RoleRow] = []
    for r in roles:
        out.append(RoleRow(
            id=r.id, name=r.name,
            description=getattr(r, "description", "") or "",
            is_system=bool(getattr(r, "is_system", False)),
            permissions=sorted(perms_by_role.get(r.id, [])),
        ))
    return out


def create_role(
    session: Session, principal: Principal, *, name: str, description: str = "", permissions: list[str] | None = None
) -> Role:
    if not principal.has(Permission.ROLES_MANAGE):
        raise PermissionDeniedError(permission=Permission.ROLES_MANAGE.value)
    name = (name or "").strip()
    if not name:
        raise ValidationError("Role name is required.", field="name")
    existing = session.scalar(select(Role).where(func.lower(Role.name) == name.lower()))
    if existing is not None:
        raise ValidationError(f"A role named '{name}' already exists.", field="name")
    _validate_permissions(permissions or [])
    r = Role(name=name, description=description)
    if hasattr(r, "is_system"):
        r.is_system = False
    session.add(r)
    session.flush()
    _replace_permissions(session, r.id, permissions or [])
    audit_record(session, principal, "role.create", entity_type="role", entity_id=r.id,
                 summary=f"Created role '{name}'.")
    return r


def update_role(
    session: Session, principal: Principal, role_id: int, *, name: str, description: str = "",
    permissions: list[str] | None = None,
) -> Role:
    if not principal.has(Permission.ROLES_MANAGE):
        raise PermissionDeniedError(permission=Permission.ROLES_MANAGE.value)
    r = session.get(Role, role_id)
    if r is None:
        raise NotFoundError("Role", role_id)
    if bool(getattr(r, "is_system", False)):
        raise ValidationError("System roles cannot be edited. Clone them instead.", field="id")
    name = (name or "").strip()
    if not name:
        raise ValidationError("Role name is required.", field="name")
    dup = session.scalar(
        select(Role).where(func.lower(Role.name) == name.lower()).where(Role.id != role_id)
    )
    if dup is not None:
        raise ValidationError(f"A role named '{name}' already exists.", field="name")
    _validate_permissions(permissions or [])
    r.name = name
    if hasattr(r, "description"):
        r.description = description
    _replace_permissions(session, r.id, permissions or [])
    session.flush()
    audit_record(session, principal, "role.update", entity_type="role", entity_id=r.id,
                 summary=f"Updated role '{name}'.")
    return r


def set_user_role(session: Session, principal: Principal, user_id: int, role_id: Optional[int]) -> User:
    if not principal.has(Permission.ROLES_MANAGE):
        raise PermissionDeniedError(permission=Permission.ROLES_MANAGE.value)
    u = get_user(session, user_id)
    if role_id is not None:
        role = session.get(Role, role_id)
        if role is None:
            raise ValidationError("Selected role does not exist.", field="role_id")
    u.role_id = role_id
    session.flush()
    audit_record(session, principal, "user.role_change", entity_type="user", entity_id=u.id,
                 summary=f"Role updated to role_id={role_id}.")
    return u


def update_user(session: Session, principal: Principal, user_id: int, *, display_name: str | None = None, username: str | None = None) -> User:
    if not principal.has(Permission.USERS_EDIT):
        raise PermissionDeniedError(permission=Permission.USERS_EDIT.value)
    u = get_user(session, user_id)
    if username is not None:
        uname = username.strip()
        if len(uname) < 3:
            raise ValidationError("Username must be at least 3 characters.", field="username")
        dup = session.scalar(select(User).where(func.lower(User.username) == uname.lower()).where(User.id != user_id))
        if dup is not None:
            raise ValidationError("That username is already taken.", field="username")
        u.username = uname
    if display_name is not None:
        u.display_name = display_name.strip()
    session.flush()
    audit_record(session, principal, "user.update", entity_type="user", entity_id=u.id,
                 summary="User profile updated.")
    return u


def activate_user(session: Session, principal: Principal, user_id: int) -> User:
    if not principal.has(Permission.USERS_EDIT):
        raise PermissionDeniedError(permission=Permission.USERS_EDIT.value)
    u = get_user(session, user_id)
    u.is_active = True
    u.failed_login_attempts = 0
    u.locked_until = None
    session.flush()
    audit_record(session, principal, "user.activate", entity_type="user", entity_id=u.id,
                 summary="User reactivated.")
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


def _validate_permissions(perms: list[str]) -> None:
    valid = {p.value for p in Permission}
    for p in perms:
        if p not in valid:
            raise ValidationError(f"Unknown permission: {p}", field="permissions")


def _replace_permissions(session: Session, role_id: int, perms: list[str]) -> None:
    from sqlalchemy import delete
    session.execute(delete(PermissionAssignment).where(PermissionAssignment.role_id == role_id))
    for p in perms:
        session.add(PermissionAssignment(role_id=role_id, permission=p))


def available_permissions() -> list[tuple[str, str, str]]:
    """Return list of (value, group, label) for the UI permission matrix."""
    groups = [
        ("Patients", ["patients.view", "patients.create", "patients.edit", "patients.delete", "patients.export"]),
        ("Clinical", ["visits.view", "visits.create", "visits.edit", "chart.view", "chart.edit",
                      "prescriptions.view", "prescriptions.create", "prescriptions.edit", "prescriptions.print",
                      "treatments.view", "treatments.create", "treatments.edit", "treatments.catalog.manage"]),
        ("Appointments & Queue", ["appointments.view", "appointments.create", "appointments.edit",
                                   "appointments.cancel", "queue.manage", "queue.reorder"]),
        ("Financial", ["invoices.view", "invoices.create", "invoices.edit", "invoices.void", "invoices.print",
                       "payments.view", "payments.create", "payments.refund",
                       "accounting.view", "accounting.manage", "reports.financial.view", "settings.financial.manage"]),
        ("Inventory", ["inventory.view", "inventory.create", "inventory.edit", "inventory.adjust", "suppliers.manage"]),
        ("Staff & Users", ["staff.view", "staff.create", "staff.edit",
                            "users.view", "users.create", "users.edit", "users.reset_password", "roles.manage"]),
        ("System", ["settings.view", "settings.manage", "dentists.manage", "clinic.manage",
                     "backup.create", "backup.restore", "backup.configure", "audit.view",
                     "activation.manage", "system.destructive", "data.export", "printers.manage",
                     "reports.view", "notifications.manage", "search.global",
                     "attachments.view", "attachments.manage"]),
    ]
    labels = {
        "patients.view": "View patients",
        "patients.create": "Create patients",
        "patients.edit": "Edit patients",
        "patients.delete": "Delete patients",
        "patients.export": "Export patients",
        "visits.view": "View visits",
        "visits.create": "Create visits",
        "visits.edit": "Edit visits",
        "chart.view": "View dental chart",
        "chart.edit": "Edit dental chart",
        "prescriptions.view": "View prescriptions",
        "prescriptions.create": "Create prescriptions",
        "prescriptions.edit": "Edit prescriptions",
        "prescriptions.print": "Print prescriptions",
        "treatments.view": "View treatments",
        "treatments.create": "Create treatments",
        "treatments.edit": "Edit treatments",
        "treatments.catalog.manage": "Manage treatment catalog",
        "appointments.view": "View appointments",
        "appointments.create": "Create appointments",
        "appointments.edit": "Edit appointments",
        "appointments.cancel": "Cancel appointments",
        "queue.manage": "Manage queue",
        "queue.reorder": "Reorder queue",
        "invoices.view": "View invoices",
        "invoices.create": "Create invoices",
        "invoices.edit": "Edit invoices",
        "invoices.void": "Void invoices",
        "invoices.print": "Print invoices",
        "payments.view": "View payments",
        "payments.create": "Record payments",
        "payments.refund": "Refund/reverse payments",
        "accounting.view": "View accounting",
        "accounting.manage": "Manage accounting",
        "reports.financial.view": "View financial reports",
        "settings.financial.manage": "Manage financial settings",
        "inventory.view": "View inventory",
        "inventory.create": "Create inventory items / purchases",
        "inventory.edit": "Edit inventory items",
        "inventory.adjust": "Adjust stock / write-off",
        "suppliers.manage": "Manage suppliers",
        "staff.view": "View staff",
        "staff.create": "Create staff",
        "staff.edit": "Edit staff",
        "users.view": "View users",
        "users.create": "Create users",
        "users.edit": "Edit users",
        "users.reset_password": "Reset passwords",
        "roles.manage": "Manage roles",
        "settings.view": "View settings",
        "settings.manage": "Manage settings",
        "dentists.manage": "Manage dentists",
        "clinic.manage": "Manage clinic profile",
        "backup.create": "Create backups",
        "backup.restore": "Restore backups",
        "backup.configure": "Configure backups",
        "audit.view": "View audit log",
        "activation.manage": "Manage activation",
        "system.destructive": "Destructive operations",
        "data.export": "Export data",
        "printers.manage": "Manage printers",
        "reports.view": "View reports",
        "notifications.manage": "Manage notifications",
        "search.global": "Global search",
        "attachments.view": "View attachments",
        "attachments.manage": "Manage attachments",
    }
    out: list[tuple[str, str, str]] = []
    for group, perms in groups:
        valid = {p.value for p in Permission}
        for p in perms:
            if p in valid:
                out.append((p, group, labels.get(p, p)))
    return out

