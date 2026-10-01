"""Inventory entities: suppliers, categories, items, movements."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dentiva.db.base import Base, TimestampMixin


class Supplier(Base, TimestampMixin):
    __tablename__ = "supplier"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_person: Mapped[str] = mapped_column(String(200), default="", server_default="")
    phone: Mapped[str] = mapped_column(String(50), default="", server_default="")
    address: Mapped[str] = mapped_column(Text, default="", server_default="")
    email: Mapped[str] = mapped_column(String(200), default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1")


class InventoryCategory(Base, TimestampMixin):
    __tablename__ = "inventory_category"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_category.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1")


class InventoryItem(Base, TimestampMixin):
    __tablename__ = "inventory_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(60), default="", server_default="", index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_category.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category: Mapped[InventoryCategory | None] = relationship("InventoryCategory", lazy="joined")
    unit: Mapped[str] = mapped_column(String(30), default="pcs", server_default="pcs")
    location: Mapped[str] = mapped_column(String(200), default="", server_default="")
    min_level_qty: Mapped[float] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    current_qty: Mapped[float] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")


class InventoryMovement(Base, TimestampMixin):
    __tablename__ = "inventory_movement"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_item.id", ondelete="RESTRICT"), nullable=False, index=True)
    movement_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    quantity_delta: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    unit_price_paisa: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("supplier.id", ondelete="SET NULL"), nullable=True)
    batch_no: Mapped[str] = mapped_column(String(100), default="", server_default="")
    expiry_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    reference: Mapped[str] = mapped_column(String(200), default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)

    supplier: Mapped[Supplier | None] = relationship("Supplier", lazy="joined")
    creator: Mapped[object | None] = relationship("User", lazy="joined", foreign_keys=[created_by])
