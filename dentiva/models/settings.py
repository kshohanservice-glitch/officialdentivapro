"""Key/value application settings and printer profiles."""
from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dentiva.db.base import Base, TimestampMixin


class AppSetting(Base):
    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="", server_default="")
    value_type: Mapped[str] = mapped_column(String(20), default="string", server_default="string")
    description: Mapped[str] = mapped_column(String(255), default="", server_default="")
    updated_at: Mapped[str] = mapped_column(String(30), default="", server_default="")


class PrinterProfile(Base, TimestampMixin):
    __tablename__ = "printer_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    paper_size: Mapped[str] = mapped_column(String(40), default="A4", server_default="A4")
    orientation: Mapped[str] = mapped_column(String(20), default="portrait", server_default="portrait")
    margin_top_mm: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    margin_bottom_mm: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    margin_left_mm: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    margin_right_mm: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    target_printer: Mapped[str] = mapped_column(String(200), default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
