"""Appointment model."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dentiva.db.base import Base, TimestampMixin


class Appointment(Base, TimestampMixin):
    __tablename__ = "appointment"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id", ondelete="CASCADE"), nullable=False, index=True)
    dentist_id: Mapped[int | None] = mapped_column(ForeignKey("dentist.id", ondelete="SET NULL"), nullable=True, index=True)
    scheduled_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=15, server_default="15")
    reason: Mapped[str] = mapped_column(String(255), default="", server_default="")
    status: Mapped[str] = mapped_column(String(30), default="scheduled", server_default="scheduled", index=True)
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
