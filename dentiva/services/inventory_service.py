# mypy: disable-error-code="assignment"
"""Inventory service — suppliers, categories, items, and stock movements.

The inventory model is deliberately simple and conservative:

* Every quantity change goes through an ``InventoryMovement`` row (audit trail).
* ``current_qty`` on the item is a *cached* rollup kept in sync via the
  service layer — never modified directly by other code. The value is
  recomputed from movements on demand for consistency checks.
* Supported movement types:
    - ``purchase``    : +qty  from a supplier (purchase receipt)
    - ``adjust_in``   : +qty  manual increase (opening stock, found, return-in)
    - ``adjust_out``  : -qty  manual decrease (damaged, expired, write-off)
    - ``consume``     : -qty  used on a visit/patient (clinical consumption)
    - ``purchase_return`` : -qty return to supplier
* All quantities are stored as Decimal(12,2) on the model; service accepts
  ``float``/``int``/``Decimal`` and normalises to Decimal with 2 decimals.
* Money values for purchases are integer paisa (same convention as the rest
  of the system).

A quantity is ``positive`` for stock-in movements and ``positive`` in the
input regardless of type; the sign is applied by the service so callers
don't have to remember signs.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dentiva.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from dentiva.core.permissions import Permission, Principal
from dentiva.models import (
    InventoryCategory,
    InventoryItem,
    InventoryMovement,
    Supplier,
)
from dentiva.services.audit_service import record as audit_record

# ------------------------------------------------------------------------- constants

TWO_PLACES = Decimal("0.01")
MOVEMENT_TYPES = {
    "purchase": +1,
    "adjust_in": +1,
    "adjust_out": -1,
    "purchase_return": -1,
    "consume": -1,
}


def _q(value: float | int | Decimal | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    d = Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return d


# ------------------------------------------------------------------------- DTOs


@dataclass
class SupplierRow:
    id: int
    name: str
    contact_person: str
    phone: str
    email: str
    address: str
    notes: str
    is_active: bool


@dataclass
class SupplierInput:
    name: str = ""
    contact_person: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    notes: str = ""
    is_active: bool = True


@dataclass
class CategoryRow:
    id: int
    name: str
    parent_id: int | None
    is_active: bool


@dataclass
class CategoryInput:
    name: str = ""
    parent_id: int | None = None
    is_active: bool = True


@dataclass
class InventoryItemRow:
    id: int
    sku: str
    name: str
    category_id: int | None
    category_name: str
    unit: str
    location: str
    min_level_qty: Decimal
    current_qty: Decimal
    notes: str
    is_low: bool


@dataclass
class InventoryItemInput:
    sku: str = ""
    name: str = ""
    category_id: int | None = None
    unit: str = "pcs"
    location: str = ""
    min_level_qty: float | Decimal = 0
    opening_qty: float | Decimal = 0
    opening_unit_price_paisa: int = 0
    notes: str = ""


@dataclass
class MovementRow:
    id: int
    item_id: int
    item_name: str
    movement_type: str
    quantity_delta: Decimal
    signed_qty: Decimal  # positive = in, negative = out, for display only
    unit_price_paisa: int
    supplier_id: int | None
    supplier_name: str
    batch_no: str
    expiry_date: dt.date | None
    reference: str
    notes: str
    created_at: dt.datetime
    created_by_name: str
    running_qty: Decimal = field(default_factory=lambda: Decimal("0.00"))


@dataclass
class StockMovementInput:
    item_id: int
    movement_type: Literal["purchase", "adjust_in", "adjust_out", "purchase_return", "consume"]
    quantity: float | Decimal = 0
    unit_price_paisa: int = 0
    supplier_id: int | None = None
    batch_no: str = ""
    expiry_date: dt.date | None = None
    reference: str = ""
    notes: str = ""


# ------------------------------------------------------------------------- suppliers


def list_suppliers(
    session: Session, principal: Principal, *, active_only: bool = False, search: str | None = None
) -> list[SupplierRow]:
    if not principal.has(Permission.SUPPLIERS_MANAGE) and not principal.has(Permission.INVENTORY_VIEW):
        raise PermissionDeniedError(permission=Permission.INVENTORY_VIEW.value)
    stmt = select(Supplier)
    if active_only:
        stmt = stmt.where(Supplier.is_active.is_(True))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Supplier.name.ilike(like))
    stmt = stmt.order_by(Supplier.name.asc())
    out: list[SupplierRow] = []
    for s in session.scalars(stmt):
        out.append(_supplier_row(s))
    return out


def get_supplier(session: Session, principal: Principal, sid: int) -> SupplierRow:
    if not principal.has(Permission.SUPPLIERS_MANAGE) and not principal.has(Permission.INVENTORY_VIEW):
        raise PermissionDeniedError(permission=Permission.INVENTORY_VIEW.value)
    s = session.get(Supplier, sid)
    if s is None:
        raise NotFoundError("Supplier", sid)
    return _supplier_row(s)


def create_supplier(session: Session, principal: Principal, data: SupplierInput) -> Supplier:
    if not principal.has(Permission.SUPPLIERS_MANAGE):
        raise PermissionDeniedError(permission=Permission.SUPPLIERS_MANAGE.value)
    name = (data.name or "").strip()
    if not name:
        raise ValidationError("Supplier name is required.", field="name")
    s = Supplier(
        name=name,
        contact_person=(data.contact_person or "").strip(),
        phone=(data.phone or "").strip(),
        email=(data.email or "").strip(),
        address=(data.address or "").strip(),
        notes=(data.notes or "").strip(),
        is_active=bool(data.is_active),
    )
    session.add(s)
    session.flush()
    audit_record(session, principal, "supplier.create", entity_type="supplier", entity_id=s.id,
                 summary=f"Added supplier '{s.name}'.")
    return s


def update_supplier(session: Session, principal: Principal, sid: int, data: SupplierInput) -> Supplier:
    if not principal.has(Permission.SUPPLIERS_MANAGE):
        raise PermissionDeniedError(permission=Permission.SUPPLIERS_MANAGE.value)
    s = session.get(Supplier, sid)
    if s is None:
        raise NotFoundError("Supplier", sid)
    name = (data.name or "").strip()
    if not name:
        raise ValidationError("Supplier name is required.", field="name")
    s.name = name
    s.contact_person = (data.contact_person or "").strip()
    s.phone = (data.phone or "").strip()
    s.email = (data.email or "").strip()
    s.address = (data.address or "").strip()
    s.notes = (data.notes or "").strip()
    s.is_active = bool(data.is_active)
    session.flush()
    audit_record(session, principal, "supplier.update", entity_type="supplier", entity_id=s.id,
                 summary=f"Updated supplier '{s.name}'.")
    return s


def _supplier_row(s: Supplier) -> SupplierRow:
    return SupplierRow(
        id=s.id, name=s.name, contact_person=s.contact_person or "",
        phone=s.phone or "", email=s.email or "", address=s.address or "",
        notes=s.notes or "", is_active=bool(s.is_active),
    )


# ------------------------------------------------------------------------- categories


def list_categories(session: Session, principal: Principal, *, active_only: bool = False) -> list[CategoryRow]:
    if not principal.has(Permission.INVENTORY_VIEW):
        raise PermissionDeniedError(permission=Permission.INVENTORY_VIEW.value)
    stmt = select(InventoryCategory)
    if active_only:
        stmt = stmt.where(InventoryCategory.is_active.is_(True))
    stmt = stmt.order_by(InventoryCategory.name.asc())
    return [
        CategoryRow(id=c.id, name=c.name, parent_id=c.parent_id, is_active=bool(c.is_active))
        for c in session.scalars(stmt)
    ]


def create_category(session: Session, principal: Principal, data: CategoryInput) -> InventoryCategory:
    if not principal.has(Permission.INVENTORY_EDIT):
        raise PermissionDeniedError(permission=Permission.INVENTORY_EDIT.value)
    name = (data.name or "").strip()
    if not name:
        raise ValidationError("Category name is required.", field="name")
    if data.parent_id is not None:
        parent = session.get(InventoryCategory, data.parent_id)
        if parent is None:
            raise ValidationError("Selected parent category does not exist.", field="parent_id")
    cat = InventoryCategory(name=name, parent_id=data.parent_id, is_active=bool(data.is_active))
    session.add(cat)
    session.flush()
    audit_record(session, principal, "inventory.category.create",
                 entity_type="inventory_category", entity_id=cat.id,
                 summary=f"Added inventory category '{name}'.")
    return cat


# ------------------------------------------------------------------------- items


def list_items(
    session: Session,
    principal: Principal,
    *,
    search: str | None = None,
    category_id: int | None = None,
    low_stock_only: bool = False,
    limit: int = 500,
) -> list[InventoryItemRow]:
    if not principal.has(Permission.INVENTORY_VIEW):
        raise PermissionDeniedError(permission=Permission.INVENTORY_VIEW.value)
    stmt = select(InventoryItem)
    if search:
        like = f"%{search}%"
        stmt = stmt.where((InventoryItem.name.ilike(like)) | (InventoryItem.sku.ilike(like)))
    if category_id is not None:
        stmt = stmt.where(InventoryItem.category_id == category_id)
    if low_stock_only:
        stmt = stmt.where(
            InventoryItem.min_level_qty > 0,
            InventoryItem.current_qty <= InventoryItem.min_level_qty,
        )
    stmt = stmt.order_by(InventoryItem.name.asc()).limit(limit)
    out: list[InventoryItemRow] = []
    for it in session.scalars(stmt):
        cat_name = it.category.name if it.category is not None else ""
        cur = Decimal(str(it.current_qty)).quantize(TWO_PLACES)
        minl = Decimal(str(it.min_level_qty)).quantize(TWO_PLACES)
        out.append(InventoryItemRow(
            id=it.id, sku=it.sku or "", name=it.name, category_id=it.category_id, category_name=cat_name,
            unit=it.unit or "pcs", location=it.location or "", min_level_qty=minl, current_qty=cur,
            notes=it.notes or "",
            is_low=bool(minl > 0 and cur <= minl),
        ))
    return out


def get_item(session: Session, principal: Principal, item_id: int) -> InventoryItemRow:
    rows = list_items(session, principal)
    for r in rows:
        if r.id == item_id:
            return r
    raise NotFoundError("InventoryItem", item_id)


def create_item(session: Session, principal: Principal, data: InventoryItemInput) -> InventoryItem:
    if not principal.has(Permission.INVENTORY_CREATE):
        raise PermissionDeniedError(permission=Permission.INVENTORY_CREATE.value)
    name = (data.name or "").strip()
    if not name:
        raise ValidationError("Item name is required.", field="name")
    unit = (data.unit or "pcs").strip() or "pcs"
    if data.category_id is not None and session.get(InventoryCategory, data.category_id) is None:
        raise ValidationError("Selected category does not exist.", field="category_id")
    opening = _q(data.opening_qty)
    if opening < 0:
        raise ValidationError("Opening quantity cannot be negative.", field="opening_qty")
    minl = _q(data.min_level_qty)
    if minl < 0:
        raise ValidationError("Minimum level cannot be negative.", field="min_level_qty")
    dup = session.scalar(
        select(InventoryItem).where(func.lower(InventoryItem.name) == name.lower())
    )
    if dup is not None:
        raise ValidationError(f"An item named '{name}' already exists.", field="name")
    it = InventoryItem(
        sku=(data.sku or "").strip(),
        name=name,
        category_id=data.category_id,
        unit=unit,
        location=(data.location or "").strip(),
        min_level_qty=minl,
        current_qty=Decimal("0.00"),
        notes=(data.notes or "").strip(),
    )
    session.add(it)
    session.flush()
    if opening > 0:
        _record_movement(
            session, principal,
            item_id=it.id,
            movement_type="adjust_in",
            quantity=opening,
            unit_price_paisa=max(0, int(data.opening_unit_price_paisa or 0)),
            supplier_id=None,
            batch_no="",
            expiry_date=None,
            reference="Opening stock",
            notes="",
        )
        it.current_qty = opening
    audit_record(session, principal, "inventory.item.create",
                 entity_type="inventory_item", entity_id=it.id,
                 summary=f"Added inventory item '{name}' (opening {opening} {unit}).")
    return it


def update_item(session: Session, principal: Principal, item_id: int, data: InventoryItemInput) -> InventoryItem:
    if not principal.has(Permission.INVENTORY_EDIT):
        raise PermissionDeniedError(permission=Permission.INVENTORY_EDIT.value)
    it = session.get(InventoryItem, item_id)
    if it is None:
        raise NotFoundError("InventoryItem", item_id)
    name = (data.name or "").strip()
    if not name:
        raise ValidationError("Item name is required.", field="name")
    if data.category_id is not None and session.get(InventoryCategory, data.category_id) is None:
        raise ValidationError("Selected category does not exist.", field="category_id")
    dup = session.scalar(
        select(InventoryItem)
        .where(func.lower(InventoryItem.name) == name.lower())
        .where(InventoryItem.id != item_id)
    )
    if dup is not None:
        raise ValidationError(f"An item named '{name}' already exists.", field="name")
    minl = _q(data.min_level_qty)
    if minl < 0:
        raise ValidationError("Minimum level cannot be negative.", field="min_level_qty")
    it.sku = (data.sku or "").strip()
    it.name = name
    it.category_id = data.category_id
    it.unit = (data.unit or "pcs").strip() or "pcs"
    it.location = (data.location or "").strip()
    it.min_level_qty = minl
    it.notes = (data.notes or "").strip()
    session.flush()
    audit_record(session, principal, "inventory.item.update",
                 entity_type="inventory_item", entity_id=it.id,
                 summary=f"Updated inventory item '{name}'.")
    return it


def delete_item(session: Session, principal: Principal, item_id: int) -> None:
    """Delete item if no movements exist; otherwise archive (clear current_qty
    to zero, deactivate-like). We disallow hard delete when movements exist
    because that would lose accounting integrity."""
    if not principal.has(Permission.INVENTORY_EDIT):
        raise PermissionDeniedError(permission=Permission.INVENTORY_EDIT.value)
    it = session.get(InventoryItem, item_id)
    if it is None:
        raise NotFoundError("InventoryItem", item_id)
    existing = session.scalar(
        select(func.count(InventoryMovement.id)).where(InventoryMovement.item_id == item_id)
    ) or 0
    if existing:
        raise ValidationError(
            "Cannot delete an item with stock history. Archive it instead (set min level 0 / "
            "use adjustments to clear stock).",
            field="id",
        )
    session.delete(it)
    session.flush()
    audit_record(session, principal, "inventory.item.delete",
                 entity_type="inventory_item", entity_id=item_id,
                 summary=f"Deleted inventory item #{item_id}.")


# ------------------------------------------------------------------------- movements


def list_movements(
    session: Session,
    principal: Principal,
    *,
    item_id: int | None = None,
    movement_type: str | None = None,
    limit: int = 500,
) -> list[MovementRow]:
    if not principal.has(Permission.INVENTORY_VIEW):
        raise PermissionDeniedError(permission=Permission.INVENTORY_VIEW.value)
    from dentiva.models import InventoryItem, User
    stmt = select(InventoryMovement).order_by(
        InventoryMovement.created_at.asc(), InventoryMovement.id.asc()
    ).limit(limit * 4)
    if item_id is not None:
        stmt = stmt.where(InventoryMovement.item_id == item_id)
    if movement_type:
        stmt = stmt.where(InventoryMovement.movement_type == movement_type)
    asc_rows = list(session.scalars(stmt))
    # Map items/users for name resolution
    item_ids = {m.item_id for m in asc_rows}
    user_ids = {m.created_by for m in asc_rows if m.created_by}
    item_names: dict[int, str] = {}
    user_names: dict[int, str] = {}
    if item_ids:
        for i in session.scalars(select(InventoryItem).where(InventoryItem.id.in_(item_ids))):
            item_names[i.id] = i.name
    if user_ids:
        for u in session.scalars(select(User).where(User.id.in_(user_ids))):
            user_names[u.id] = u.display_name
    running: dict[int, Decimal] = {}
    asc_result: list[MovementRow] = []
    for m in asc_rows:
        delta = Decimal(str(m.quantity_delta)).quantize(TWO_PLACES)
        running[m.item_id] = running.get(m.item_id, Decimal("0.00")) + delta
        asc_result.append(MovementRow(
            id=m.id, item_id=m.item_id, item_name=item_names.get(m.item_id, f"#{m.item_id}"),
            movement_type=m.movement_type,
            quantity_delta=delta.copy_abs(), signed_qty=delta,
            unit_price_paisa=int(m.unit_price_paisa or 0),
            supplier_id=m.supplier_id,
            supplier_name=(m.supplier.name if m.supplier is not None else ""),
            batch_no=m.batch_no or "", expiry_date=m.expiry_date,
            reference=m.reference or "", notes=m.notes or "",
            created_at=m.created_at,
            created_by_name=user_names.get(m.created_by, "") if m.created_by else "",
            running_qty=running[m.item_id].quantize(TWO_PLACES),
        ))
    # Newest first, capped at limit.
    return list(reversed(asc_result[-limit:]))


def record_movement(session: Session, principal: Principal, data: StockMovementInput) -> InventoryMovement:
    """Record a stock movement. Permission: INVENTORY_ADJUST for manual adjustments,
    INVENTORY_CREATE for purchases; for convenience we require INVENTORY_ADJUST for all
    manual changes. Consume-type movements are normally created by visit/invoice services,
    so they are allowed with INVENTORY_EDIT to keep clinical workflow friction low."""
    if data.movement_type in ("adjust_in", "adjust_out", "purchase_return"):
        if not principal.has(Permission.INVENTORY_ADJUST):
            raise PermissionDeniedError(permission=Permission.INVENTORY_ADJUST.value)
    elif data.movement_type == "purchase":
        if not principal.has(Permission.INVENTORY_CREATE):
            raise PermissionDeniedError(permission=Permission.INVENTORY_CREATE.value)
    else:  # consume
        if not principal.has(Permission.INVENTORY_EDIT):
            raise PermissionDeniedError(permission=Permission.INVENTORY_EDIT.value)
    qty = _q(data.quantity)
    if qty <= 0:
        raise ValidationError("Quantity must be greater than zero.", field="quantity")
    it = session.get(InventoryItem, data.item_id)
    if it is None:
        raise NotFoundError("InventoryItem", data.item_id)
    if data.supplier_id is not None and data.supplier_id != 0:
        sup = session.get(Supplier, data.supplier_id)
        if sup is None:
            raise ValidationError("Selected supplier does not exist.", field="supplier_id")
    else:
        data.supplier_id = None
    sign = MOVEMENT_TYPES.get(data.movement_type)
    if sign is None:
        raise ValidationError(f"Unknown movement type '{data.movement_type}'.", field="movement_type")
    signed_qty = qty * sign
    new_qty = Decimal(str(it.current_qty)) + signed_qty
    if new_qty < 0 and data.movement_type in ("adjust_out", "consume", "purchase_return"):
        raise ValidationError(
            f"Stock would go negative ({new_qty} {it.unit}). Check the quantity.",
            field="quantity",
        )
    mv = _record_movement(
        session, principal,
        item_id=it.id,
        movement_type=data.movement_type,
        quantity=qty,
        unit_price_paisa=max(0, int(data.unit_price_paisa or 0)),
        supplier_id=data.supplier_id,
        batch_no=(data.batch_no or "").strip(),
        expiry_date=data.expiry_date,
        reference=(data.reference or "").strip(),
        notes=(data.notes or "").strip(),
    )
    it.current_qty = new_qty.quantize(TWO_PLACES)
    session.flush()
    return mv


def _record_movement(
    session: Session, principal: Principal, *,
    item_id: int, movement_type: str, quantity: Decimal,
    unit_price_paisa: int, supplier_id: int | None,
    batch_no: str, expiry_date: dt.date | None, reference: str, notes: str,
) -> InventoryMovement:
    sign = MOVEMENT_TYPES[movement_type]
    mv = InventoryMovement(
        item_id=item_id,
        movement_type=movement_type,
        quantity_delta=(quantity * sign).quantize(TWO_PLACES),
        unit_price_paisa=unit_price_paisa,
        supplier_id=supplier_id,
        batch_no=batch_no,
        expiry_date=expiry_date,
        reference=reference,
        notes=notes,
        created_by=principal.user_id,
    )
    session.add(mv)
    session.flush()
    dirn = "in" if sign > 0 else "out"
    audit_record(
        session, principal, f"inventory.movement.{movement_type}",
        entity_type="inventory_item", entity_id=item_id,
        summary=f"Stock {dirn} {quantity} of item #{item_id} ({movement_type}).",
    )
    return mv


# ------------------------------------------------------------------------- helpers / reports


def low_stock_items(session: Session, principal: Principal) -> list[InventoryItemRow]:
    """Convenience used by the dashboard and notifications."""
    return list_items(session, principal, low_stock_only=True)


def stock_value_paisa(session: Session, principal: Principal) -> int:
    """Total value of on-hand stock using last-known unit price per item.

    We compute this as SUM(current_qty * last_unit_price) where last_unit_price
    is the most recent purchase/adjust_in movement's unit_price_paisa for that
    item. If no purchase exists we fall back to 0.
    """
    if not principal.has(Permission.INVENTORY_VIEW):
        raise PermissionDeniedError(permission=Permission.INVENTORY_VIEW.value)
    # Simple approach: iterate items and multiply by the latest in-price.
    total = Decimal("0")
    for it in session.scalars(select(InventoryItem)):
        cur = Decimal(str(it.current_qty))
        if cur <= 0:
            continue
        last_in = session.scalar(
            select(InventoryMovement.unit_price_paisa)
            .where(
                InventoryMovement.item_id == it.id,
                InventoryMovement.movement_type.in_(["purchase", "adjust_in"]),
                InventoryMovement.unit_price_paisa > 0,
            )
            .order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
            .limit(1)
        )
        price = int(last_in or 0)
        total += cur * Decimal(price) / Decimal(100)
    return int((total * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
