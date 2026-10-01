"""Security models: users, roles, permission assignments, audit log."""
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from .staff import Staff

from dentiva.core.dates import TZ
from dentiva.db.base import Base, TimestampMixin


class Role(Base, TimestampMixin):
    __tablename__ = "role"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="", server_default="")
    is_system: Mapped[bool] = mapped_column(default=False, server_default="0")

    permissions: Mapped[list[PermissionAssignment]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    users: Mapped[list[User]] = relationship(back_populates="role")


class PermissionAssignment(Base):
    __tablename__ = "permission_assignment"

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id", ondelete="CASCADE"), index=True)
    permission: Mapped[str] = mapped_column(String(80), nullable=False)

    role: Mapped[Role] = relationship(back_populates="permissions")


class User(Base, TimestampMixin):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    role_id: Mapped[int | None] = mapped_column(ForeignKey("role.id"), nullable=True, index=True)
    staff_id: Mapped[int | None] = mapped_column(
        ForeignKey("staff.id", ondelete="SET NULL"), nullable=True, index=True
    )
    staff: Mapped[Staff | None] = relationship(  # type: ignore[name-defined]
        "Staff", foreign_keys=[staff_id]
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1")
    is_superuser: Mapped[bool] = mapped_column(default=False, server_default="0")
    must_change_password: Mapped[bool] = mapped_column(default=False, server_default="0")
    failed_login_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    password_set_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    role: Mapped[Role | None] = relationship(back_populates="users")

    def permissions_list(self) -> list[str]:
        if self.role is None:
            return []
        return [p.permission for p in self.role.permissions]


class AuditEvent(Base):
    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[dt.datetime] = mapped_column(
        default=lambda: dt.datetime.now(tz=TZ).replace(tzinfo=None),
        server_default=None,
        nullable=False,
        index=True,
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), default="", server_default="", index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_or_machine: Mapped[str] = mapped_column(String(200), default="", server_default="")
