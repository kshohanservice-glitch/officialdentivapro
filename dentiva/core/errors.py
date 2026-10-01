"""Typed exception hierarchy for Dentiva Pro.

All service-layer errors inherit from :class:`DentivaError` so UI code can map
them to human-friendly messages without parsing stack traces.

The ``user_message`` attribute is always safe to show in dialogs — it never
contains raw SQL, stack frames, or file paths.
"""
from __future__ import annotations

from typing import Any


class DentivaError(Exception):
    """Base class for all Dentiva Pro application errors."""

    #: Message suitable for display in a modal dialog.
    user_message: str

    def __init__(self, user_message: str, *, detail: str | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.user_message


class ValidationError(DentivaError):
    """Raised when user input fails validation (field-specific)."""

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, detail=detail)
        self.field = field


class AuthenticationError(DentivaError):
    """Login failure, locked account, invalid session, etc."""


class PermissionDeniedError(DentivaError):
    """Raised by the policy engine when a principal lacks a required permission."""

    def __init__(self, permission: str | None = None, detail: str | None = None) -> None:
        message = "You do not have permission to perform this action."
        super().__init__(message, detail=detail)
        self.permission = permission


class NotFoundError(DentivaError):
    """Requested entity does not exist (or was soft-deleted)."""

    def __init__(self, entity: str, entity_id: Any | None = None) -> None:
        msg = f"{entity} not found." if entity_id is None else f"{entity} #{entity_id} not found."
        super().__init__(msg)
        self.entity = entity
        self.entity_id = entity_id


class ConflictError(DentivaError):
    """Operation would violate a uniqueness or state constraint (e.g. double-booking)."""


class ImmutableError(DentivaError):
    """Attempt to modify a finalized/immutable record (posted invoice, finalized Rx)."""


class DatabaseError(DentivaError):
    """Wraps unexpected DB errors in a user-friendly form."""

    def __init__(self, detail: str | None = None) -> None:
        super().__init__("A database error occurred. Please restart Dentiva Pro if the problem persists.", detail=detail)


class BackupRestoreError(DentivaError):
    """Backup creation/restore failure."""


class ActivationError(DentivaError):
    """Activation failure or tampering."""


class PrintError(DentivaError):
    """Printing/PDF generation failure."""


class AttachmentError(DentivaError):
    """Attachment upload / open failure."""
