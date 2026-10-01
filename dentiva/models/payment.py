"""Payment methods and payments."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dentiva.core.dates import TZ
from dentiva.db.base import Base, TimestampMixin


class PaymentMethod(Base, TimestampMixin):
    __tablename__ = "payment_method"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)  # cash, bkash, nagad, …
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Payment(Base, TimestampMixin):
    __tablename__ = "payment"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoice.id", ondelete="RESTRICT"), nullable=False, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id", ondelete="RESTRICT"), nullable=False, index=True)
    method_id: Mapped[int] = mapped_column(ForeignKey("payment_method.id", ondelete="RESTRICT"), nullable=False, index=True)
    amount_paisa: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_no: Mapped[str] = mapped_column(String(100), default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    paid_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(tz=TZ).replace(tzinfo=None), nullable=False, index=True
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    reversed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    reversal_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
