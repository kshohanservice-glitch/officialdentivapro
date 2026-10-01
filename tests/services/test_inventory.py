"""Inventory service tests — items, suppliers, categories, stock movements,
low-stock detection, and the in-stock value rollup."""
from __future__ import annotations

import pytest
from dentiva.core.errors import ValidationError
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import inventory_service


def _make_item(uow, principal, **kw):
    data = inventory_service.InventoryItemInput(
        name=kw.get("name", "Syringe A2"),
        sku=kw.get("sku", ""),
        unit=kw.get("unit", "pcs"),
        min_level_qty=kw.get("min_level_qty", 5),
        opening_qty=kw.get("opening_qty", 0),
        opening_unit_price_paisa=kw.get("opening_unit_price_paisa", 0),
    )
    return inventory_service.create_item(uow.session, principal, data)


def test_create_item_opening_stock(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        it = inventory_service.create_item(
            uow.session, admin_principal,
            inventory_service.InventoryItemInput(
                name="Composite Syringe", sku="C-A2", unit="pcs",
                min_level_qty=3, opening_qty=10, opening_unit_price_paisa=150000,
            ),
        )
        uow.commit()
        # Reload via list: opening_qty becomes an adjust_in movement
        items = inventory_service.list_items(uow.session, admin_principal)
    rows = [x for x in items if x.id == it.id]
    assert len(rows) == 1
    assert rows[0].current_qty == pytest.approx(10, abs=0.01)
    assert rows[0].is_low is False  # 10 > 3
    # Movements recorded
    with UnitOfWork(session_factory) as uow:
        mvs = inventory_service.list_movements(uow.session, admin_principal, item_id=it.id)
    assert len(mvs) == 1
    assert mvs[0].movement_type == "adjust_in"
    assert mvs[0].signed_qty == pytest.approx(10, abs=0.01)


def test_low_stock_detection(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        _make_item(uow, admin_principal, name="Gauze", min_level_qty=10, opening_qty=10)
        _make_item(uow, admin_principal, name="Gloves", min_level_qty=20, opening_qty=5)
        _make_item(uow, admin_principal, name="Etchant", min_level_qty=0, opening_qty=0)
        uow.commit()
        low = inventory_service.low_stock_items(uow.session, admin_principal)
        names = [x.name for x in low]
    assert "Gloves" in names
    assert "Gauze" in names  # current == min => low per service
    assert "Etchant" not in names  # min_level 0 is "not tracked"


def test_adjustment_out_negative_blocked(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        it = _make_item(uow, admin_principal, name="Bur", opening_qty=2)
        with pytest.raises(ValidationError) as ei:
            inventory_service.record_movement(
                uow.session, admin_principal,
                inventory_service.StockMovementInput(
                    item_id=it.id, movement_type="adjust_out", quantity=5,
                ),
            )
        assert "negative" in ei.value.user_message.lower()


def test_purchase_and_writeoff_ledger(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        sup = inventory_service.create_supplier(
            uow.session, admin_principal,
            inventory_service.SupplierInput(name="Dental Supply Co.", phone="01700000000"),
        )
        it = _make_item(uow, admin_principal, name="Mask")
        # purchase 100 @ 5tk each
        inventory_service.record_movement(
            uow.session, admin_principal,
            inventory_service.StockMovementInput(
                item_id=it.id, movement_type="purchase", quantity=100,
                unit_price_paisa=500, supplier_id=sup.id, reference="PO-001",
            ),
        )
        # consume 10
        inventory_service.record_movement(
            uow.session, admin_principal,
            inventory_service.StockMovementInput(
                item_id=it.id, movement_type="consume", quantity=10,
            ),
        )
        uow.commit()
        items = inventory_service.list_items(uow.session, admin_principal)
        row = next(x for x in items if x.id == it.id)
        assert row.current_qty == pytest.approx(90, abs=0.01)
        mvs = inventory_service.list_movements(uow.session, admin_principal, item_id=it.id)
    # mvs returned newest-first
    types = [m.movement_type for m in mvs]
    assert types == ["consume", "purchase"]  # opening adjust_in? we used opening_qty=0 so no
    # Running qty for the newest row (consume) should be 90; for the older purchase row, 100; then 0.
    # (Because we started at 0.)
    assert mvs[0].running_qty == pytest.approx(90, abs=0.01)
    assert mvs[1].running_qty == pytest.approx(100, abs=0.01)


def test_stock_value(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        it1 = inventory_service.create_item(
            uow.session, admin_principal,
            inventory_service.InventoryItemInput(name="A", opening_qty=10, opening_unit_price_paisa=10000),
        )
        it2 = inventory_service.create_item(
            uow.session, admin_principal,
            inventory_service.InventoryItemInput(name="B", opening_qty=5, opening_unit_price_paisa=20000),
        )
        uow.commit()
        value = inventory_service.stock_value_paisa(uow.session, admin_principal)
    # 10 * 100tk + 5 * 200tk = 1000 + 1000 = 2000 tk = 200000 paisa
    assert value == 200_000


def test_duplicate_item_rejected(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        _make_item(uow, admin_principal, name="Gauze Roll")
        with pytest.raises(ValidationError):
            _make_item(uow, admin_principal, name="gauze roll")  # case-insensitive


def test_supplier_crud(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        s = inventory_service.create_supplier(
            uow.session, admin_principal,
            inventory_service.SupplierInput(name="Acme Co", phone="01800"),
        )
        uow.commit()
        sid = s.id
    with UnitOfWork(session_factory) as uow:
        row = inventory_service.get_supplier(uow.session, admin_principal, sid)
        assert row.name == "Acme Co"
        assert row.phone == "01800"
        # name required
        with pytest.raises(ValidationError):
            inventory_service.create_supplier(
                uow.session, admin_principal, inventory_service.SupplierInput(name="")
            )


def test_item_delete_blocked_with_movements(session_factory, admin_principal):
    with UnitOfWork(session_factory) as uow:
        it = inventory_service.create_item(
            uow.session, admin_principal,
            inventory_service.InventoryItemInput(name="Temp", opening_qty=5),
        )
        uow.commit()
        with pytest.raises(ValidationError):
            inventory_service.delete_item(uow.session, admin_principal, it.id)


def test_permission_gating(session_factory):
    """A principal without INVENTORY_VIEW cannot list items."""
    from dentiva.core.errors import PermissionDeniedError
    from dentiva.core.permissions import Principal
    nobody = Principal(user_id=None, username="nobody", display_name="nobody",
                       permissions=(), is_superuser=False)
    with UnitOfWork(session_factory) as uow:
        with pytest.raises(PermissionDeniedError):
            inventory_service.list_items(uow.session, nobody)
        with pytest.raises(PermissionDeniedError):
            inventory_service.create_item(
                uow.session, nobody,
                inventory_service.InventoryItemInput(name="x"),
            )
