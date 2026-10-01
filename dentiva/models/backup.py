"""Backup history records."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dentiva.db.base import Base


class BackupRecord(Base):
    __tablename__ = "backup_record"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="started", server_default="started", index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    triggered_by: Mapped[str] = mapped_column(String(20), default="manual", server_default="manual")
    schema_version: Mapped[str] = mapped_column(String(40), default="", server_default="")
    checksum: Mapped[str] = mapped_column(String(128), default="", server_default="")
    error_message: Mapped[str] = mapped_column(Text, default="", server_default="")
