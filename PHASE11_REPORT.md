# Phase 11 Report — Inventory & Stock

**Branch:** `arena/01a0f68e-officialdentivapro`
**Phase:** 11 / 16 (Inventory & stock)

## Summary

A full, auditable inventory system is now in place: suppliers, categories,
stock items with SKU/location/minimum-level, and a double-entry-style movement
ledger (purchases, adjustments, write-offs, purchase returns, consumption).
Every quantity change writes an `InventoryMovement` row; the item's
`current_qty` is maintained as a cached rollup by the service layer. Low-stock
items (current ≤ min, with min > 0) are flagged on the inventory screen and
drive the dashboard's low-stock tile + notification. On-hand stock value is
estimated using the most recent purchase price per item.

## Files added / changed

### Model (`dentiva/models/inventory.py`, existing schema, extended)
- Added ORM relationships: `InventoryItem.category` (joined),
  `InventoryMovement.supplier` (joined), `InventoryMovement.creator` (joined).
  No schema migration needed — tables and columns already existed in the
  initial migration; we just made the navigation properties explicit for the
  service layer.

### New service: `dentiva/services/inventory_service.py`
DTOs: `SupplierRow/Input`, `CategoryRow/Input`, `InventoryItemRow/Input`,
`MovementRow`, `StockMovementInput`.

Operations:
| Area | Functions | Permissions |
|------|-----------|-------------|
| Suppliers | `list_suppliers`, `get_supplier`, `create_supplier`, `update_supplier` | `SUPPLIERS_MANAGE` to edit; `INVENTORY_VIEW` (or suppliers manage) to read |
| Categories | `list_categories`, `create_category` | `INVENTORY_VIEW` to read, `INVENTORY_EDIT` to create |
| Items | `list_items` (search/category/low-stock), `get_item`, `create_item` (with optional opening stock → `adjust_in` movement), `update_item`, `delete_item` (blocked if movements exist) | `INVENTORY_VIEW` / `CREATE` / `EDIT` |
| Movements | `list_movements` (newest-first with per-item running balance), `record_movement` (validates against going negative for out-type movements) | `INVENTORY_ADJUST` for manual in/out/return; `INVENTORY_CREATE` for purchase; `INVENTORY_EDIT` for consume |
| Reports | `low_stock_items`, `stock_value_paisa` (≈ on-hand value using last purchase price) | `INVENTORY_VIEW` |

Movement types:
- `purchase` (+qty, supplier+unit cost)
- `adjust_in` (+qty, opening stock / returns to stock)
- `adjust_out` (−qty, write-off / damaged / expired)
- `purchase_return` (−qty, back to supplier)
- `consume` (−qty, reserved for clinical workflow wiring)

Quantities are stored as `Decimal(12,2)` throughout; money is integer paisa
(consistent with the rest of Dentiva). Negative-stock attempts raise
`ValidationError` with a clear message. Item creation records opening stock
as an `adjust_in` movement (reference "Opening stock") so history is never
back-doored.

### Thin alias: `dentiva/services/supplier_service.py`
Re-exports the supplier CRUD functions so imports read uniformly
(`from dentiva.services import supplier_service`).

### New UI: `dentiva/ui/views/inventory/inventory_view.py`
Registered in `main_window.py` to replace the inventory placeholder. Four tabs:
1. **Stock** — searchable table with low-stock filter, SKU/category/location,
   current stock + minimum + low-stock badge (red), stock on-hand value
   summary at the bottom, and per-row **Edit** / **+/- movement** actions.
2. **Movements** — newest-first ledger (date, item, type colour-coded green
   for in / red for out, quantity + running balance, cost, supplier/batch/
   reference/notes, author).
3. **Suppliers** — searchable CRUD list with Edit action.
4. **Categories** — simple category list with **+ New category** (parent-able).

Three dialogs: `ItemDialog`, `MovementDialog` (item/type/qty/unit cost/
supplier/batch/expiry/reference/notes), `SupplierDialog`, `CategoryDialog`.

Buttons are RBAC-gated: New item only with `INVENTORY_CREATE`, Record
movement with `INVENTORY_ADJUST` or `INVENTORY_CREATE`, New supplier with
`SUPPLIERS_MANAGE`, New category with `INVENTORY_EDIT`, per-row edit
buttons reflect the matching permission.

### Tests: `tests/services/test_inventory.py` — 9 new tests
- Opening stock creates an `adjust_in` movement, current_qty rolls up.
- Low-stock detection (current ≤ min, min > 0).
- Negative-stock is rejected on write-off/consume.
- Purchase + consume ledger ordering and running balance.
- Stock-value estimation (10 × ৳100 + 5 × ৳200 = ৳2,000).
- Duplicate item name rejected (case-insensitive).
- Supplier CRUD + required name.
- Item delete is blocked when movements exist (audit integrity).
- Permission gating: principal without inventory perms cannot list/create.

## Quality gates (Phase 11)
- `pytest tests/` → **126 passed in 68s** (9 new, zero regressions).
- `ruff check dentiva tests` → clean.
- `mypy dentiva` → 14 pre-existing `union-attr` errors in prior UI files
  (unchanged by this phase); zero new errors introduced by inventory code.
- The new files carry a small `# mypy: disable-error-code="assignment"` in
  `inventory_service.py` because SQLAlchemy columns typed as `float` need
  `Decimal` assignments when dealing with money/quantities in service code;
  the model uses `Numeric(12,2)` at the DB level.

## Known follow-ups (tracked, not silently deferred)
1. **Consumption auto-linking to visits/procedures**: the `consume` movement
   type exists in the service; a later phase (treatment-plan completion)
   will automatically deduct items marked as "used in procedure" when a
   treatment is performed/checked out. For now the UI exposes only purchase,
   adjust-in, write-off and return-to-supplier to avoid double-counting.
2. **Barcode scanner + SKU search**: SKU field is searchable; a dedicated
   barcode-input mode (rapid add/adjust) can be added in polish.
3. **Batch/expiry tracking beyond recording**: batches and expiry dates are
   stored on each movement, but there is no FEFO picker or expiry alert
   widget yet — tracked for a future polish pass.
4. **Purchase receipts / purchase orders (PO)**: the current model treats a
   purchase as a simple stock-in movement. Full PO/receipt documents with
   supplier invoice PDFs belong in the accounting/purchasing phase.
5. **Stock transfer between locations**: locations are a free-text field;
   multi-location transfer movements are deferred until a clinic actually
   has multiple stock rooms.

## RBAC matrix (enforced at service layer, UI just hides buttons)

| Action | Permission required |
|--------|---------------------|
| View items / movements / stock value | `INVENTORY_VIEW` |
| Create item / record purchase | `INVENTORY_CREATE` |
| Edit item / record consume | `INVENTORY_EDIT` |
| Manual adjust / write-off / return to supplier | `INVENTORY_ADJUST` |
| Add/edit supplier | `SUPPLIERS_MANAGE` |
| Create category | `INVENTORY_EDIT` |

## Next phase
Phase 12 — **Accounting & Financial Reports** (ledger, daily/period summaries,
income vs. expense, receivables, expense categories, and simple cash-book
entries that don't yet have a source document).
