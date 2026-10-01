"""Treatment catalog and patient treatment records."""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dentiva.db.base import Base, TimestampMixin


class TreatmentCatalog(Base, TimestampMixin):
    __tablename__ = "treatment_catalog"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    category: Mapped[str] = mapped_column(String(100), default="", server_default="", index=True)
    default_price_paisa: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")


class TreatmentRecord(Base, TimestampMixin):
    __tablename__ = "treatment_record"

    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visit.id", ondelete="CASCADE"), nullable=False, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id", ondelete="RESTRICT"), nullable=False, index=True)
    dentist_id: Mapped[int | None] = mapped_column(ForeignKey("dentist.id", ondelete="SET NULL"), nullable=True)
    catalog_id: Mapped[int | None] = mapped_column(
        ForeignKey("treatment_catalog.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name_at_service_time: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    tooth_codes: Mapped[str] = mapped_column(String(255), default="", server_default="")
    price_paisa: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
