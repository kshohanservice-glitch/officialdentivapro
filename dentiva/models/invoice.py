"""Invoice and invoice line items."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dentiva.core.dates import TZ
from dentiva.db.base import Base, TimestampMixin


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoice"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id", ondelete="RESTRICT"), nullable=False, index=True)
    dentist_id: Mapped[int | None] = mapped_column(ForeignKey("dentist.id", ondelete="SET NULL"), nullable=True, index=True)
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("visit.id", ondelete="SET NULL"), nullable=True, index=True)
    date: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(tz=TZ).replace(tzinfo=None), nullable=False, index=True
    )
    subtotal_paisa: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    discount_paisa: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tax_paisa: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_paisa: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    paid_paisa: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    due_paisa: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(20), default="unpaid", server_default="unpaid", index=True)
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    is_posted: Mapped[bool] = mapped_column(default=False, server_default="0", index=True)
    posted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    voided_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    void_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)


class InvoiceLineItem(Base, TimestampMixin):
    __tablename__ = "invoice_line_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoice.id", ondelete="CASCADE"), nullable=False, index=True)
    item_type: Mapped[str] = mapped_column(String(30), default="custom", server_default="custom")  # treatment/catalog/custom
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    unit_price_paisa: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    discount_paisa: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    line_total_paisa: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
