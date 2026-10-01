"""Accounting categories and entries."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from dentiva.db.base import Base, TimestampMixin


class AccountingCategory(Base, TimestampMixin):
    __tablename__ = "accounting_category"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # income | expense
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounting_category.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1")


class AccountingEntry(Base, TimestampMixin):
    __tablename__ = "accounting_entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_category.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # income | expense
    amount_paisa: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_method_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_method.id", ondelete="SET NULL"), nullable=True
    )
    reference: Mapped[str] = mapped_column(String(200), default="", server_default="")
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    related_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoice.id", ondelete="SET NULL"), nullable=True
    )
    related_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
