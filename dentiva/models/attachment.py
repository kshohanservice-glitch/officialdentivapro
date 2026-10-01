"""Patient / record attachments."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dentiva.db.base import Base, TimestampMixin


class Attachment(Base, TimestampMixin):
    """Attached file. Files are stored inside the application data directory
    (``attachments/<yyyymm>/<uuid>.<ext>``) and referenced via
    ``stored_filename``. The ``attachable_type`` / ``attachable_id`` pair
    gives us lightweight polymorphism without SQLAlchemy-utils generic FKs."""

    __tablename__ = "attachment"

    id: Mapped[int] = mapped_column(primary_key=True)
    attachable_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)  # patient, visit, prescription, …
    attachable_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="", server_default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    title: Mapped[str] = mapped_column(String(255), default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
