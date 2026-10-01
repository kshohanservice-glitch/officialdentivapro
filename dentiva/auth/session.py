"""Session state and Principal construction."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from dentiva.core.dates import now
from dentiva.core.permissions import Permission, Principal


@dataclass
class Session:
    """Runtime session state. Holds the authenticated principal and the
    auto-lock deadline. The UI timer resets :attr:`lock_deadline` on user
    activity (mouse/key events on the main window)."""

    principal: Principal | None = None
    lock_deadline: datetime | None = None
    lock_minutes: int | None = None  # None = never auto-lock
    created_at: datetime = field(default_factory=now)

    # --- authentication state ---

    @property
    def is_authenticated(self) -> bool:
        return self.principal is not None

    def login(self, principal: Principal, lock_minutes: int | None) -> None:
        self.principal = principal
        self.lock_minutes = lock_minutes
        self.created_at = now()
        self.touch()

    def logout(self) -> None:
        self.principal = None
        self.lock_deadline = None
        self.lock_minutes = None

    # --- auto lock ---

    def touch(self) -> None:
        """Reset the auto-lock deadline (called on user activity)."""
        if self.principal is None or self.lock_minutes is None or self.lock_minutes <= 0:
            self.lock_deadline = None
            return
        self.lock_deadline = now() + timedelta(minutes=self.lock_minutes)

    def should_lock(self) -> bool:
        if self.principal is None:
            return False
        if self.lock_deadline is None:
            return False
        return now() >= self.lock_deadline

    def require_permission(self, permission: Permission) -> None:
        if self.principal is None:
            from dentiva.core.errors import AuthenticationError
            raise AuthenticationError("You must log in to perform this action.")
        from dentiva.core.permissions import policy
        policy.require(self.principal, permission)
