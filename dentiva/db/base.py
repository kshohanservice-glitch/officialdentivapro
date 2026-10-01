"""SQLAlchemy DeclarativeBase and common mixins."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from dentiva.core.dates import TZ

# Naming convention for constraints — makes Alembic migrations deterministic.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Adds ``created_at`` (auto-set) and ``updated_at`` (auto-update) columns."""

    created_at: Mapped[dt.datetime] = mapped_column(
        default=lambda: dt.datetime.now(tz=TZ).replace(tzinfo=None),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        default=lambda: dt.datetime.now(tz=TZ).replace(tzinfo=None),
        onupdate=lambda: dt.datetime.now(tz=TZ).replace(tzinfo=None),
        server_default=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Adds ``deleted_at`` column. Soft-deleted records are filtered out by default."""

    deleted_at: Mapped[dt.datetime | None] = mapped_column(nullable=True, default=None)
