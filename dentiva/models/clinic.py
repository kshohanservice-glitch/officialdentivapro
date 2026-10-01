"""Clinic/business profile (single row)."""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dentiva.db.base import Base, TimestampMixin


class ClinicProfile(Base, TimestampMixin):
    __tablename__ = "clinic_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tagline: Mapped[str] = mapped_column(String(255), default="", server_default="")
    logo_path: Mapped[str] = mapped_column(String(500), default="", server_default="")
    address: Mapped[str] = mapped_column(Text, default="", server_default="")
    phone: Mapped[str] = mapped_column(String(50), default="", server_default="")
    email: Mapped[str] = mapped_column(String(200), default="", server_default="")
    website: Mapped[str] = mapped_column(String(200), default="", server_default="")
    prescription_footer: Mapped[str] = mapped_column(Text, default="", server_default="")
    currency_code: Mapped[str] = mapped_column(String(8), default="BDT", server_default="BDT")
    setup_completed: Mapped[bool] = mapped_column(default=False, server_default="0")
