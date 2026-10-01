"""Inventory view — items, stock movements, suppliers, and low-stock alerts.

Tabs:
  * Stock (items list with current qty, min level, low-stock badge)
  * Movements (ledger of all stock-in/out)
  * Suppliers
  * Categories
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

from dentiva.core.errors import DentivaError, ValidationError
from dentiva.core.money import format_bdt
from dentiva.core.permissions import Permission
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import inventory_service
from dentiva.ui.design_tokens import Spacing
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from dentiva.core.permissions import Principal


# ------------------------------------------------------------------------- helpers

def _qty_str(v: Decimal) -> str:
    return f"{v:,.2f}".rstrip("0").rstrip(".") if v != 0 else "0"


# ------------------------------------------------------------------------- Item dialog


class ItemDialog(QDialog):
    def __init__(self, session_factory, principal, *, item_id: int | None = None, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        self._item_id = item_id
        self.setWindowTitle("Edit item" if item_id else "New inventory item")
        self.setMinimumWidth(460)
        self.setModal(True)
        f = QFormLayout(self)

        self._name = QLineEdit(self)
        self._name.setPlaceholderText("e.g. Composite Syringe A2")
        self._sku = QLineEdit(self)
        self._sku.setPlaceholderText("SKU / barcode (optional)")
        self._category = QComboBox(self)
        self._category.addItem("(none)", None)
        with UnitOfWork(session_factory) as uow:
            cats = inventory_service.list_categories(uow.session, principal)
        for c in cats:
            self._category.addItem(c.name, c.id)
        self._unit = QLineEdit(self)
        self._unit.setPlaceholderText("pcs, box, pack, vial…")
        self._unit.setText("pcs")
        self._location = QLineEdit(self)
        self._location.setPlaceholderText("Shelf A / Cabinet 2 …")
        self._min = QDoubleSpinBox(self)
        self._min.setRange(0, 1_000_000)
        self._min.setDecimals(2)
        self._min.setSingleStep(1)
        self._opening = QDoubleSpinBox(self)
        self._opening.setRange(0, 1_000_000)
        self._opening.setDecimals(2)
        self._opening.setSingleStep(1)
        self._opening_price = QSpinBox(self)
        self._opening_price.setRange(0, 10_000_000)
        self._opening_price.setSuffix(" ৳")
        self._opening_price.setSingleStep(50)
        self._notes = QLineEdit(self)
        self._notes.setPlaceholderText("Optional notes")

        f.addRow("Name *", self._name)
        f.addRow("SKU", self._sku)
        f.addRow("Category", self._category)
        f.addRow("Unit", self._unit)
        f.addRow("Location", self._location)
        f.addRow("Minimum level (low-stock)", self._min)
        if item_id is None:
            f.addRow("Opening quantity", self._opening)
            f.addRow("Opening unit cost", self._opening_price)
        f.addRow("Notes", self._notes)

        if item_id is not None:
            with UnitOfWork(session_factory) as uow:
                row = inventory_service.get_item(uow.session, principal, item_id)
            self._name.setText(row.name)
            self._sku.setText(row.sku)
            idx = self._category.findData(row.category_id)
            if idx >= 0:
                self._category.setCurrentIndex(idx)
            self._unit.setText(row.unit)
            self._location.setText(row.location)
            self._min.setValue(float(row.min_level_qty))
            self._notes.setText(row.notes)

        self._err = QLabel("", self)
        self._err.setObjectName("DpFieldError")
        self._err.setWordWrap(True)
        f.addRow(self._err)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _save(self) -> None:
        self._err.setText("")
        data = inventory_service.InventoryItemInput(
            sku=self._sku.text().strip(),
            name=self._name.text().strip(),
            category_id=self._category.currentData(),
            unit=self._unit.text().strip() or "pcs",
            location=self._location.text().strip(),
            min_level_qty=self._min.value(),
            opening_qty=self._opening.value() if self._item_id is None else 0,
            opening_unit_price_paisa=int(self._opening_price.value()) * 100 if self._item_id is None else 0,
            notes=self._notes.text().strip(),
        )
        try:
            with UnitOfWork(self._sf) as uow:
                if self._item_id is None:
                    inventory_service.create_item(uow.session, self._p, data)
                else:
                    inventory_service.update_item(uow.session, self._p, self._item_id, data)
                uow.commit()
        except ValidationError as e:
            self._err.setText(e.user_message)
            return
        except DentivaError as e:
            self._err.setText(e.user_message)
            return
        self.accept()


# ------------------------------------------------------------------------- Movement dialog

class MovementDialog(QDialog):
    def __init__(self, session_factory, principal, *, item_id: int | None = None, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        self.setWindowTitle("Record stock movement")
        self.setMinimumWidth(420)
        self.setModal(True)
        f = QFormLayout(self)

        self._item = QComboBox(self)
        with UnitOfWork(session_factory) as uow:
            items = inventory_service.list_items(uow.session, principal)
            sups = inventory_service.list_suppliers(uow.session, principal, active_only=True)
        for it in items:
            self._item.addItem(f"{it.name} (stock {_qty_str(it.current_qty)} {it.unit})", it.id)
        self._type = QComboBox(self)
        self._type.addItem("Purchase (stock in)", "purchase")
        self._type.addItem("Adjustment / Return to stock", "adjust_in")
        self._type.addItem("Write-off / stock out", "adjust_out")
        self._type.addItem("Return to supplier", "purchase_return")
        # "consume" is reserved for automated clinical usage; users can still
        # write-off. We expose consume via service but not UI to avoid confusion.

        self._qty = QDoubleSpinBox(self)
        self._qty.setRange(0.01, 1_000_000)
        self._qty.setDecimals(2)
        self._qty.setSingleStep(1)
        self._price = QSpinBox(self)
        self._price.setRange(0, 10_000_000)
        self._price.setSuffix(" ৳")
        self._price.setSingleStep(50)
        self._supplier = QComboBox(self)
        self._supplier.addItem("(none)", None)
        for s in sups:
            self._supplier.addItem(s.name, s.id)
        self._batch = QLineEdit(self)
        self._batch.setPlaceholderText("Batch / lot #")
        self._expiry = QDateEdit(self)
        self._expiry.setCalendarPopup(True)
        self._expiry.setDate(QDate(2099, 12, 31))
        self._expiry.setSpecialValueText(" ")
        self._expiry.setDisplayFormat("dd MMM yyyy")
        self._ref = QLineEdit(self)
        self._ref.setPlaceholderText("Invoice #, receipt #, …")
        self._notes = QLineEdit(self)
        self._notes.setPlaceholderText("Optional notes")

        if item_id is not None:
            idx = self._item.findData(item_id)
            if idx >= 0:
                self._item.setCurrentIndex(idx)

        f.addRow("Item *", self._item)
        f.addRow("Movement type *", self._type)
        f.addRow("Quantity *", self._qty)
        f.addRow("Unit cost (for purchase)", self._price)
        f.addRow("Supplier", self._supplier)
        f.addRow("Batch #", self._batch)
        f.addRow("Expiry", self._expiry)
        f.addRow("Reference", self._ref)
        f.addRow("Notes", self._notes)

        self._err = QLabel("", self)
        self._err.setObjectName("DpFieldError")
        self._err.setWordWrap(True)
        f.addRow(self._err)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _save(self) -> None:
        self._err.setText("")
        exp_py: dt.date | None = None
        qd = self._expiry.date()
        if qd.year() < 2099:
            exp_py = dt.date(qd.year(), qd.month(), qd.day())
        exp = exp_py
        data = inventory_service.StockMovementInput(
            item_id=int(self._item.currentData()),
            movement_type=self._type.currentData(),
            quantity=self._qty.value(),
            unit_price_paisa=int(self._price.value()) * 100,
            supplier_id=self._supplier.currentData(),
            batch_no=self._batch.text().strip(),
            expiry_date=exp,
            reference=self._ref.text().strip(),
            notes=self._notes.text().strip(),
        )
        try:
            with UnitOfWork(self._sf) as uow:
                inventory_service.record_movement(uow.session, self._p, data)
                uow.commit()
        except ValidationError as e:
            self._err.setText(e.user_message)
            return
        except DentivaError as e:
            self._err.setText(e.user_message)
            return
        self.accept()


# ------------------------------------------------------------------------- Supplier dialog

class SupplierDialog(QDialog):
    def __init__(self, session_factory, principal, *, supplier_id: int | None = None, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        self._sid = supplier_id
        self.setWindowTitle("Edit supplier" if supplier_id else "New supplier")
        self.setMinimumWidth(420)
        self.setModal(True)
        f = QFormLayout(self)
        self._name = QLineEdit(self)
        self._name.setPlaceholderText("Supplier / company name")
        self._contact = QLineEdit(self)
        self._contact.setPlaceholderText("Contact person")
        self._phone = QLineEdit(self)
        self._email = QLineEdit(self)
        self._address = QLineEdit(self)
        self._notes = QLineEdit(self)
        f.addRow("Name *", self._name)
        f.addRow("Contact person", self._contact)
        f.addRow("Phone", self._phone)
        f.addRow("Email", self._email)
        f.addRow("Address", self._address)
        f.addRow("Notes", self._notes)
        if supplier_id is not None:
            with UnitOfWork(session_factory) as uow:
                s = inventory_service.get_supplier(uow.session, principal, supplier_id)
            self._name.setText(s.name)
            self._contact.setText(s.contact_person)
            self._phone.setText(s.phone)
            self._email.setText(s.email)
            self._address.setText(s.address)
            self._notes.setText(s.notes)
        self._err = QLabel("", self)
        self._err.setObjectName("DpFieldError")
        self._err.setWordWrap(True)
        f.addRow(self._err)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _save(self) -> None:
        self._err.setText("")
        data = inventory_service.SupplierInput(
            name=self._name.text().strip(),
            contact_person=self._contact.text().strip(),
            phone=self._phone.text().strip(),
            email=self._email.text().strip(),
            address=self._address.text().strip(),
            notes=self._notes.text().strip(),
        )
        try:
            with UnitOfWork(self._sf) as uow:
                if self._sid is None:
                    inventory_service.create_supplier(uow.session, self._p, data)
                else:
                    inventory_service.update_supplier(uow.session, self._p, self._sid, data)
                uow.commit()
        except ValidationError as e:
            self._err.setText(e.user_message)
            return
        except DentivaError as e:
            self._err.setText(e.user_message)
            return
        self.accept()


# ------------------------------------------------------------------------- Category dialog

class CategoryDialog(QDialog):
    def __init__(self, session_factory, principal, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        self.setWindowTitle("New category")
        self.setMinimumWidth(360)
        self.setModal(True)
        f = QFormLayout(self)
        self._name = QLineEdit(self)
        self._name.setPlaceholderText("Consumables, Instruments, Medication…")
        self._parent = QComboBox(self)
        self._parent.addItem("(top-level)", None)
        with UnitOfWork(session_factory) as uow:
            for c in inventory_service.list_categories(uow.session, principal):
                self._parent.addItem(c.name, c.id)
        f.addRow("Name *", self._name)
        f.addRow("Parent", self._parent)
        self._err = QLabel("", self)
        self._err.setObjectName("DpFieldError")
        self._err.setWordWrap(True)
        f.addRow(self._err)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _save(self) -> None:
        self._err.setText("")
        data = inventory_service.CategoryInput(name=self._name.text().strip(), parent_id=self._parent.currentData())
        try:
            with UnitOfWork(self._sf) as uow:
                inventory_service.create_category(uow.session, self._p, data)
                uow.commit()
        except ValidationError as e:
            self._err.setText(e.user_message)
            return
        except DentivaError as e:
            self._err.setText(e.user_message)
            return
        self.accept()


# ------------------------------------------------------------------------- Main view


class InventoryView(QWidget):
    def __init__(self, session_factory, principal: Principal, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.S4)

        title = QLabel("Inventory & stock", self)
        title.setObjectName("DpPageTitle")
        sub = QLabel(
            "Track consumables, materials and medications. Every stock change "
            "is recorded as an auditable movement.", self
        )
        sub.setObjectName("DpPageSubtitle")
        root.addWidget(title)
        root.addWidget(sub)

        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_items_tab(), "Stock")
        self._tabs.addTab(self._build_movements_tab(), "Movements")
        self._tabs.addTab(self._build_suppliers_tab(), "Suppliers")
        self._tabs.addTab(self._build_categories_tab(), "Categories")
        self._tabs.currentChanged.connect(lambda _i: self._reload_active())
        root.addWidget(self._tabs, 1)

    def refresh(self) -> None:
        self._reload_active()

    def _reload_active(self) -> None:
        idx = self._tabs.currentIndex()
        if idx == 0:
            self._reload_items()
        elif idx == 1:
            self._reload_movements()
        elif idx == 2:
            self._reload_suppliers()
        elif idx == 3:
            self._reload_categories()

    # --- Items
    def _build_items_tab(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0,0,0,0)
        lay.setSpacing(Spacing.S3)
        bar = QHBoxLayout()
        bar.setSpacing(Spacing.S2)
        self._item_search = QLineEdit(w)
        self._item_search.setPlaceholderText("Search items…")
        self._item_search.textChanged.connect(lambda _t: self._reload_items())
        self._low_only = QCheckBox("Low stock only", w)
        self._low_only.toggled.connect(lambda _v: self._reload_items())
        self._new_item = QPushButton("+ New item", w)
        self._new_item.setProperty("variant", "primary")
        self._new_item.clicked.connect(self._on_new_item)
        self._new_item.setVisible(self._p.has(Permission.INVENTORY_CREATE))
        self._mv_btn = QPushButton("Record movement", w)
        self._mv_btn.setProperty("variant", "primary-subtle")
        self._mv_btn.clicked.connect(self._on_new_movement)
        self._mv_btn.setVisible(self._p.has(Permission.INVENTORY_ADJUST) or self._p.has(Permission.INVENTORY_CREATE))
        bar.addWidget(self._item_search, 1)
        bar.addWidget(self._low_only)
        bar.addWidget(self._mv_btn)
        bar.addWidget(self._new_item)
        lay.addLayout(bar)
        self._items_tbl = QTableWidget(0, 7, w)
        self._items_tbl.setObjectName("DpDataTable")
        self._items_tbl.setHorizontalHeaderLabels(["Name", "SKU", "Category", "Location", "Stock", "Min", "Actions"])
        self._items_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._items_tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._items_tbl.verticalHeader().setVisible(False)
        hh = self._items_tbl.horizontalHeader()
        for col, mode in enumerate([
            QHeaderView.Stretch, QHeaderView.ResizeToContents, QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents, QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents, QHeaderView.ResizeToContents,
        ]):
            hh.setSectionResizeMode(col, mode)
        lay.addWidget(self._items_tbl, 1)
        return w

    def _reload_items(self) -> None:
        search = self._item_search.text().strip() or None
        try:
            with UnitOfWork(self._sf) as uow:
                items = inventory_service.list_items(
                    uow.session, self._p, search=search, low_stock_only=self._low_only.isChecked()
                )
                value_paisa = inventory_service.stock_value_paisa(uow.session, self._p)
        except DentivaError:
            return
        self._items_tbl.setRowCount(0)
        for it in items:
            r = self._items_tbl.rowCount()
            self._items_tbl.insertRow(r)
            name_item = QTableWidgetItem(it.name + ("  ⚠ low" if it.is_low else ""))
            if it.is_low:
                name_item.setForeground(Qt.GlobalColor.red)
            self._items_tbl.setItem(r, 0, name_item)
            self._items_tbl.setItem(r, 1, QTableWidgetItem(it.sku))
            self._items_tbl.setItem(r, 2, QTableWidgetItem(it.category_name))
            self._items_tbl.setItem(r, 3, QTableWidgetItem(it.location))
            self._items_tbl.setItem(r, 4, QTableWidgetItem(f"{_qty_str(it.current_qty)} {it.unit}"))
            self._items_tbl.setItem(r, 5, QTableWidgetItem(f"{_qty_str(it.min_level_qty)} {it.unit}"))
            cell = QWidget(self._items_tbl)
            ch = QHBoxLayout(cell)
            ch.setContentsMargins(4,2,4,2)
            ch.setSpacing(4)
            edit = QPushButton("Edit", cell)
            edit.setEnabled(self._p.has(Permission.INVENTORY_EDIT))
            edit.clicked.connect(lambda _=False, iid=it.id: self._on_edit_item(iid))
            mv = QPushButton("+/-", cell)
            mv.setToolTip("Record stock movement for this item")
            mv.setEnabled(self._p.has(Permission.INVENTORY_ADJUST) or self._p.has(Permission.INVENTORY_CREATE))
            mv.clicked.connect(lambda _=False, iid=it.id: self._on_new_movement(iid))
            ch.addWidget(edit)
            ch.addWidget(mv)
            self._items_tbl.setCellWidget(r, 6, cell)
        # Footer summary
        if items:
            r = self._items_tbl.rowCount()
            self._items_tbl.insertRow(r)
            summary = QTableWidgetItem(
                f"{len(items)} item(s) shown   ·   Stock on-hand value ≈ {format_bdt(value_paisa)}"
            )
            f = summary.font()
            f.setItalic(True)
            summary.setFont(f)
            self._items_tbl.setItem(r, 0, summary)
            for col in range(1, 7):
                self._items_tbl.setItem(r, col, QTableWidgetItem(""))

    def _on_new_item(self) -> None:
        if ItemDialog(self._sf, self._p, parent=self).exec():
            self._reload_items()

    def _on_edit_item(self, item_id: int) -> None:
        if ItemDialog(self._sf, self._p, item_id=item_id, parent=self).exec():
            self._reload_items()

    def _on_new_movement(self, item_id: int | None = None) -> None:
        if MovementDialog(self._sf, self._p, item_id=item_id, parent=self).exec():
            self._reload_items()
            self._reload_movements()

    # --- Movements
    def _build_movements_tab(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0,0,0,0)
        lay.setSpacing(Spacing.S3)
        bar = QHBoxLayout()
        info = QLabel("Full stock movement ledger. Newest first.", w)
        info.setObjectName("DpMutedLabel")
        self._mv_refresh = QPushButton("Refresh", w)
        self._mv_refresh.clicked.connect(self._reload_movements)
        bar.addWidget(info, 1)
        bar.addWidget(self._mv_refresh)
        lay.addLayout(bar)
        self._mv_tbl = QTableWidget(0, 7, w)
        self._mv_tbl.setObjectName("DpDataTable")
        self._mv_tbl.setHorizontalHeaderLabels(["Date", "Item", "Type", "Qty", "Cost", "Supplier / Ref", "By"])
        self._mv_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._mv_tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._mv_tbl.verticalHeader().setVisible(False)
        hh = self._mv_tbl.horizontalHeader()
        for col, mode in enumerate([
            QHeaderView.ResizeToContents, QHeaderView.Stretch, QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents, QHeaderView.ResizeToContents, QHeaderView.Stretch,
            QHeaderView.ResizeToContents,
        ]):
            hh.setSectionResizeMode(col, mode)
        lay.addWidget(self._mv_tbl, 1)
        return w

    def _reload_movements(self) -> None:
        try:
            with UnitOfWork(self._sf) as uow:
                mvs = inventory_service.list_movements(uow.session, self._p, limit=500)
        except DentivaError:
            return
        self._mv_tbl.setRowCount(0)
        type_label = {
            "purchase": "Purchase +",
            "adjust_in": "In +",
            "adjust_out": "Out −",
            "purchase_return": "Returned −",
            "consume": "Consumed −",
        }
        for m in mvs:
            r = self._mv_tbl.rowCount()
            self._mv_tbl.insertRow(r)
            date_str = m.created_at.strftime("%d %b %Y %H:%M")
            self._mv_tbl.setItem(r, 0, QTableWidgetItem(date_str))
            self._mv_tbl.setItem(r, 1, QTableWidgetItem(m.item_name))
            t_item = QTableWidgetItem(type_label.get(m.movement_type, m.movement_type))
            if m.signed_qty < 0:
                t_item.setForeground(Qt.GlobalColor.red)
            else:
                t_item.setForeground(Qt.GlobalColor.darkGreen)
            self._mv_tbl.setItem(r, 2, t_item)
            self._mv_tbl.setItem(r, 3, QTableWidgetItem(f"{_qty_str(m.quantity_delta.copy_abs())}  ({_qty_str(m.running_qty)})"))
            self._mv_tbl.setItem(r, 4, QTableWidgetItem(format_bdt(m.unit_price_paisa) if m.unit_price_paisa else ""))
            ref_bits = []
            if m.supplier_name:
                ref_bits.append(m.supplier_name)
            if m.batch_no:
                ref_bits.append(f"batch {m.batch_no}")
            if m.reference:
                ref_bits.append(m.reference)
            if m.notes:
                ref_bits.append(m.notes)
            self._mv_tbl.setItem(r, 5, QTableWidgetItem(" · ".join(ref_bits)))
            self._mv_tbl.setItem(r, 6, QTableWidgetItem(m.created_by_name))

    # --- Suppliers
    def _build_suppliers_tab(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0,0,0,0)
        lay.setSpacing(Spacing.S3)
        bar = QHBoxLayout()
        self._sup_search = QLineEdit(w)
        self._sup_search.setPlaceholderText("Search suppliers…")
        self._sup_search.textChanged.connect(lambda _t: self._reload_suppliers())
        self._new_sup = QPushButton("+ New supplier", w)
        self._new_sup.setProperty("variant", "primary")
        self._new_sup.clicked.connect(self._on_new_supplier)
        self._new_sup.setVisible(self._p.has(Permission.SUPPLIERS_MANAGE))
        bar.addWidget(self._sup_search, 1)
        bar.addWidget(self._new_sup)
        lay.addLayout(bar)
        self._sup_tbl = QTableWidget(0, 6, w)
        self._sup_tbl.setObjectName("DpDataTable")
        self._sup_tbl.setHorizontalHeaderLabels(["Name", "Contact", "Phone", "Email", "Address", "Actions"])
        self._sup_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._sup_tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._sup_tbl.verticalHeader().setVisible(False)
        hh = self._sup_tbl.horizontalHeader()
        for col, mode in enumerate([
            QHeaderView.Stretch, QHeaderView.ResizeToContents, QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents, QHeaderView.Stretch, QHeaderView.ResizeToContents,
        ]):
            hh.setSectionResizeMode(col, mode)
        lay.addWidget(self._sup_tbl, 1)
        return w

    def _reload_suppliers(self) -> None:
        search = self._sup_search.text().strip() or None
        try:
            with UnitOfWork(self._sf) as uow:
                sups = inventory_service.list_suppliers(uow.session, self._p, search=search)
        except DentivaError:
            return
        self._sup_tbl.setRowCount(0)
        for s in sups:
            r = self._sup_tbl.rowCount()
            self._sup_tbl.insertRow(r)
            self._sup_tbl.setItem(r, 0, QTableWidgetItem(s.name + ("  (inactive)" if not s.is_active else "")))
            self._sup_tbl.setItem(r, 1, QTableWidgetItem(s.contact_person))
            self._sup_tbl.setItem(r, 2, QTableWidgetItem(s.phone))
            self._sup_tbl.setItem(r, 3, QTableWidgetItem(s.email))
            self._sup_tbl.setItem(r, 4, QTableWidgetItem(s.address))
            cell = QWidget(self._sup_tbl)
            ch = QHBoxLayout(cell)
            ch.setContentsMargins(4,2,4,2)
            ch.setSpacing(4)
            edit = QPushButton("Edit", cell)
            edit.setEnabled(self._p.has(Permission.SUPPLIERS_MANAGE))
            edit.clicked.connect(lambda _=False, sid=s.id: self._on_edit_supplier(sid))
            ch.addWidget(edit)
            self._sup_tbl.setCellWidget(r, 5, cell)

    def _on_new_supplier(self) -> None:
        if SupplierDialog(self._sf, self._p, parent=self).exec():
            self._reload_suppliers()
            self._reload_items()

    def _on_edit_supplier(self, sid: int) -> None:
        if SupplierDialog(self._sf, self._p, supplier_id=sid, parent=self).exec():
            self._reload_suppliers()

    # --- Categories
    def _build_categories_tab(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0,0,0,0)
        lay.setSpacing(Spacing.S3)
        bar = QHBoxLayout()
        info = QLabel("Categories organise your stock items.", w)
        info.setObjectName("DpMutedLabel")
        self._new_cat = QPushButton("+ New category", w)
        self._new_cat.setProperty("variant", "primary")
        self._new_cat.clicked.connect(self._on_new_category)
        self._new_cat.setVisible(self._p.has(Permission.INVENTORY_EDIT))
        bar.addWidget(info, 1)
        bar.addWidget(self._new_cat)
        lay.addLayout(bar)
        self._cat_tbl = QTableWidget(0, 2, w)
        self._cat_tbl.setObjectName("DpDataTable")
        self._cat_tbl.setHorizontalHeaderLabels(["Name", "Parent"])
        self._cat_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._cat_tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._cat_tbl.verticalHeader().setVisible(False)
        hh = self._cat_tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        lay.addWidget(self._cat_tbl, 1)
        return w

    def _reload_categories(self) -> None:
        try:
            with UnitOfWork(self._sf) as uow:
                cats = inventory_service.list_categories(uow.session, self._p)
                names = {c.id: c.name for c in cats}
        except DentivaError:
            return
        self._cat_tbl.setRowCount(0)
        for c in cats:
            r = self._cat_tbl.rowCount()
            self._cat_tbl.insertRow(r)
            self._cat_tbl.setItem(r, 0, QTableWidgetItem(c.name + ("  (inactive)" if not c.is_active else "")))
            self._cat_tbl.setItem(r, 1, QTableWidgetItem(names.get(c.parent_id, "") if c.parent_id else "(top-level)"))

    def _on_new_category(self) -> None:
        if CategoryDialog(self._sf, self._p, parent=self).exec():
            self._reload_categories()
            self._reload_items()
