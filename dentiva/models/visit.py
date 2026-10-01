"""Visit + tooth reference + dental chart findings."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dentiva.core.dates import TZ
from dentiva.db.base import Base, TimestampMixin


class ToothReference(Base):
    """Static reference table of all supported teeth (adult FDI 11-48 and pediatric 51-85)."""

    __tablename__ = "tooth_reference"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)  # e.g. "11", "53"
    name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    quadrant: Mapped[int] = mapped_column(Integer, nullable=False)
    is_pediatric: Mapped[bool] = mapped_column(default=False, server_default="0")
    order_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    notation_ada: Mapped[str] = mapped_column(String(8), default="", server_default="")


class Visit(Base, TimestampMixin):
    __tablename__ = "visit"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id", ondelete="RESTRICT"), nullable=False, index=True)
    dentist_id: Mapped[int | None] = mapped_column(ForeignKey("dentist.id", ondelete="SET NULL"), nullable=True, index=True)
    visit_date: Mapped[dt.datetime] = mapped_column(
        DateTime,
        default=lambda: dt.datetime.now(tz=TZ).replace(tzinfo=None),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(255), default="", server_default="")
    chief_complaint: Mapped[str] = mapped_column(Text, default="", server_default="")
    on_examination: Mapped[str] = mapped_column(Text, default="", server_default="")
    advice: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open", index=True)
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class DentalChartFinding(Base, TimestampMixin):
    """Per-visit, per-tooth finding (historical)."""

    __tablename__ = "dental_chart_finding"

    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visit.id", ondelete="CASCADE"), nullable=False, index=True)
    tooth_code: Mapped[str] = mapped_column(
        ForeignKey("tooth_reference.code", ondelete="RESTRICT"), nullable=False, index=True
    )
    finding: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    surface: Mapped[str] = mapped_column(String(20), default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
