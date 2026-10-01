"""Permission constants and policy engine.

The permission set is intentionally granular. Service methods receive the
current :class:`Principal` explicitly (no thread-local magic) and call
``policy.require(principal, Permission.SOMETHING)`` at the top — this makes
bypass-by-UI-hiding impossible.
"""
from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from .errors import PermissionDeniedError


class Permission(str, Enum):
    # Patients
    PATIENTS_VIEW = "patients.view"
    PATIENTS_CREATE = "patients.create"
    PATIENTS_EDIT = "patients.edit"
    PATIENTS_DELETE = "patients.delete"
    PATIENTS_EXPORT = "patients.export"

    # Clinical
    VISITS_VIEW = "visits.view"
    VISITS_CREATE = "visits.create"
    VISITS_EDIT = "visits.edit"
    DENTAL_CHART_VIEW = "chart.view"
    DENTAL_CHART_EDIT = "chart.edit"
    PRESCRIPTIONS_VIEW = "prescriptions.view"
    PRESCRIPTIONS_CREATE = "prescriptions.create"
    PRESCRIPTIONS_EDIT = "prescriptions.edit"
    PRESCRIPTIONS_PRINT = "prescriptions.print"
    TREATMENTS_VIEW = "treatments.view"
    TREATMENTS_CREATE = "treatments.create"
    TREATMENTS_EDIT = "treatments.edit"
    TREATMENTS_CATALOG_MANAGE = "treatments.catalog.manage"

    # Appointments & Queue
    APPOINTMENTS_VIEW = "appointments.view"
    APPOINTMENTS_CREATE = "appointments.create"
    APPOINTMENTS_EDIT = "appointments.edit"
    APPOINTMENTS_CANCEL = "appointments.cancel"
    QUEUE_MANAGE = "queue.manage"
    QUEUE_REORDER = "queue.reorder"

    # Financial
    INVOICES_VIEW = "invoices.view"
    INVOICES_CREATE = "invoices.create"
    INVOICES_EDIT = "invoices.edit"
    INVOICES_VOID = "invoices.void"
    INVOICES_PRINT = "invoices.print"
    PAYMENTS_VIEW = "payments.view"
    PAYMENTS_CREATE = "payments.create"
    PAYMENTS_REFUND = "payments.refund"
    ACCOUNTING_VIEW = "accounting.view"
    ACCOUNTING_MANAGE = "accounting.manage"
    FINANCIAL_REPORTS_VIEW = "reports.financial.view"
    FINANCIAL_SETTINGS_MANAGE = "settings.financial.manage"

    # Inventory
    INVENTORY_VIEW = "inventory.view"
    INVENTORY_CREATE = "inventory.create"
    INVENTORY_EDIT = "inventory.edit"
    INVENTORY_ADJUST = "inventory.adjust"
    SUPPLIERS_MANAGE = "suppliers.manage"

    # Staff & Users
    STAFF_VIEW = "staff.view"
    STAFF_CREATE = "staff.create"
    STAFF_EDIT = "staff.edit"
    USERS_VIEW = "users.view"
    USERS_CREATE = "users.create"
    USERS_EDIT = "users.edit"
    USERS_RESET_PASSWORD = "users.reset_password"
    ROLES_MANAGE = "roles.manage"

    # System
    SETTINGS_VIEW = "settings.view"
    SETTINGS_MANAGE = "settings.manage"
    DENTISTS_MANAGE = "dentists.manage"
    CLINIC_PROFILE_MANAGE = "clinic.manage"
    BACKUP_CREATE = "backup.create"
    BACKUP_RESTORE = "backup.restore"
    BACKUP_CONFIGURE = "backup.configure"
    AUDIT_LOG_VIEW = "audit.view"
    ACTIVATION_MANAGE = "activation.manage"
    DESTRUCTIVE_OPERATIONS = "system.destructive"
    DATA_EXPORT = "data.export"
    PRINTERS_MANAGE = "printers.manage"
    VIEW_REPORTS = "reports.view"
    NOTIFICATIONS_MANAGE = "notifications.manage"
    SEARCH_GLOBAL = "search.global"
    ATTACHMENTS_VIEW = "attachments.view"
    ATTACHMENTS_MANAGE = "attachments.manage"


class Principal:
    """Authenticated actor passed to every service method."""

    __slots__ = ("display_name", "is_superuser", "permissions", "user_id", "username")

    def __init__(
        self,
        user_id: int,
        username: str,
        display_name: str,
        permissions: Iterable[Permission | str],
        *,
        is_superuser: bool = False,
    ) -> None:
        self.user_id = user_id
        self.username = username
        self.display_name = display_name
        self.is_superuser = is_superuser
        self.permissions: set[Permission] = set()
        for p in permissions:
            if isinstance(p, Permission):
                self.permissions.add(p)
            else:
                try:
                    self.permissions.add(Permission(p))
                except ValueError:
                    # Unknown permission strings are ignored (forward-compat).
                    continue

    def has(self, permission: Permission) -> bool:
        if self.is_superuser:
            return True
        return permission in self.permissions

    def can_view_financials(self) -> bool:
        """Convenience for filtering financial widgets/queries."""
        return self.is_superuser or any(
            p in self.permissions
            for p in (
                Permission.INVOICES_VIEW,
                Permission.PAYMENTS_VIEW,
                Permission.ACCOUNTING_VIEW,
                Permission.FINANCIAL_REPORTS_VIEW,
            )
        )


class Policy:
    """Centralised permission checker. Instantiated once; passed to services."""

    @staticmethod
    def require(principal: Principal, permission: Permission) -> None:
        if not principal.has(permission):
            raise PermissionDeniedError(permission=permission.value)

    @staticmethod
    def any(principal: Principal, *permissions: Permission) -> None:
        """Require at least one of ``permissions``."""
        for p in permissions:
            if principal.has(p):
                return
        raise PermissionDeniedError(permission=",".join(p.value for p in permissions))


policy = Policy()
