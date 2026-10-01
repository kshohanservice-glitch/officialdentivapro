"""Patient model."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dentiva.db.base import Base, SoftDeleteMixin, TimestampMixin


class Patient(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "patient"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    dob: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    age_cache: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str] = mapped_column(String(20), default="", server_default="", index=True)
    blood_group: Mapped[str] = mapped_column(String(10), default="", server_default="")
    address: Mapped[str] = mapped_column(Text, default="", server_default="")
    phone: Mapped[str] = mapped_column(String(50), default="", server_default="", index=True)
    emergency_phone: Mapped[str] = mapped_column(String(50), default="", server_default="")
    email: Mapped[str] = mapped_column(String(200), default="", server_default="")
    chief_complaint: Mapped[str] = mapped_column(Text, default="", server_default="")
    medical_history: Mapped[str] = mapped_column(Text, default="", server_default="")
    allergies: Mapped[str] = mapped_column(Text, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    last_visit_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    visit_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
