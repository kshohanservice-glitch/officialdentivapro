"""Prescriptions, prescription medicines, and clinical template options."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dentiva.core.dates import TZ
from dentiva.db.base import Base, TimestampMixin


class ClinicalTemplateOption(Base, TimestampMixin):
    """Configurable quick-select entries for CC / OE / Advice sections."""

    __tablename__ = "clinical_template_option"

    id: Mapped[int] = mapped_column(primary_key=True)
    section_key: Mapped[str] = mapped_column(String(30), nullable=False, index=True)  # cc | oe | advice
    display_text: Mapped[str] = mapped_column(String(300), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")


class Prescription(Base, TimestampMixin):
    __tablename__ = "prescription"

    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("visit.id", ondelete="SET NULL"), nullable=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id", ondelete="RESTRICT"), nullable=False, index=True)
    dentist_id: Mapped[int | None] = mapped_column(ForeignKey("dentist.id", ondelete="SET NULL"), nullable=True, index=True)
    date: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(tz=TZ).replace(tzinfo=None), nullable=False, index=True
    )
    chief_complaint: Mapped[str] = mapped_column(Text, default="", server_default="")
    on_examination: Mapped[str] = mapped_column(Text, default="", server_default="")
    advice: Mapped[str] = mapped_column(Text, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    finalized: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", index=True)
    finalized_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)


class PrescriptionMedicine(Base, TimestampMixin):
    __tablename__ = "prescription_medicine"

    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey("prescription.id", ondelete="CASCADE"), nullable=False, index=True)
    idx: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # ordering
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    form: Mapped[str] = mapped_column(String(50), default="", server_default="")  # tablet, capsule, cream, …
    strength: Mapped[str] = mapped_column(String(100), default="", server_default="")
    frequency_morning: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    frequency_noon: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    frequency_night: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    meal_relation: Mapped[str] = mapped_column(String(20), default="after", server_default="after")  # before/after/with/none
    duration_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    quantity: Mapped[str] = mapped_column(String(50), default="", server_default="")
    instructions: Mapped[str] = mapped_column(String(300), default="", server_default="")
