"""Treatment catalog view — browse/add/edit treatments and see usage counts."""
from __future__ import annotations

from typing import TYPE_CHECKING

from dentiva.core.errors import DentivaError, ValidationError
from dentiva.core.money import format_bdt
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import treatment_service
from dentiva.ui.design_tokens import Spacing
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from dentiva.core.permissions import Principal


class TreatmentCatalogDialog(QDialog):
    def __init__(self, session_factory, principal, *, catalog_id=None, parent=None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal
        self._catalog_id = catalog_id
        self.setWindowTitle("Edit treatment" if catalog_id else "New treatment")
        self.setModal(True)
        self.setMinimumWidth(420)
        f = QFormLayout(self)
        self._name = QLineEdit(self)
        self._name.setPlaceholderText("e.g. Composite filling (Class II)")
        self._category = QLineEdit(self)
        self._category.setPlaceholderText("Restorative, Endodontics, Surgery, …")
        self._price = QSpinBox(self)
        self._price.setRange(0, 10_000_000)
        self._price.setSuffix(" ৳")
        self._price.setSingleStep(50)
        self._price.setMaximumWidth(180)
        self._desc = QLineEdit(self)
        self._desc.setPlaceholderText("Optional description")
        f.addRow("Name *", self._name)
        f.addRow("Category", self._category)
        f.addRow("Default price", self._price)
        f.addRow("Description", self._desc)
        if catalog_id is not None:
            with UnitOfWork(session_factory) as uow:
                row = treatment_service.get_catalog(uow.session, principal, catalog_id)
            self._name.setText(row.name)
            self._category.setText(row.category)
            self._price.setValue(row.default_price_paisa // 100)
            self._desc.setText(row.description)
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
        data = treatment_service.TreatmentCatalogInput(
            name=self._name.text().strip(),
            category=self._category.text().strip(),
            default_price_paisa=int(self._price.value()) * 100,
            description=self._desc.text().strip(),
            is_active=True,
        )
        try:
            with UnitOfWork(self._session_factory) as uow:
                if self._catalog_id is None:
                    treatment_service.create_catalog_item(uow.session, self._principal, data)
                else:
                    treatment_service.update_catalog_item(
                        uow.session, self._principal, self._catalog_id, data
                    )
                uow.commit()
        except ValidationError as e:
            self._err.setText(e.user_message)
            return
        except DentivaError as e:
            self._err.setText(e.user_message)
            return
        self.accept()


class TreatmentsView(QWidget):
    def __init__(self, session_factory, principal: Principal, parent=None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.S4)

        title = QLabel("Treatment catalog", self)
        title.setObjectName("DpPageTitle")
        sub = QLabel(
            "Add and edit clinic services; prices are snapshotted on each visit "
            "so future edits don't change past invoices.",
            self,
        )
        sub.setObjectName("DpPageSubtitle")
        root.addWidget(title)
        root.addWidget(sub)

        bar = QHBoxLayout()
        bar.setSpacing(Spacing.S2)
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Search treatments…")
        self._search.textChanged.connect(lambda _t: self._reload())
        bar.addWidget(self._search, 1)
        self._new_btn = QPushButton("+ New treatment", self)
        self._new_btn.setProperty("variant", "primary")
        self._new_btn.clicked.connect(self._on_new)
        from dentiva.core.permissions import Permission
        self._new_btn.setVisible(self._principal.has(Permission.TREATMENTS_CATALOG_MANAGE))
        bar.addWidget(self._new_btn)
        root.addLayout(bar)

        self._table = QTableWidget(0, 5, self)
        self._table.setObjectName("DpDataTable")
        self._table.setHorizontalHeaderLabels(
            ["Name", "Category", "Default price", "Usage", "Actions"]
        )
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        root.addWidget(self._table, 1)
        self._reload()

    def refresh(self) -> None:
        self._reload()

    def _reload(self) -> None:
        search = self._search.text().strip() or None
        with UnitOfWork(self._session_factory) as uow:
            items = treatment_service.list_catalog(
                uow.session, self._principal, search=search
            )
        self._table.setRowCount(0)
        for t in items:
            r = self._table.rowCount()
            self._table.insertRow(r)
            suffix = "  (inactive)" if not t.is_active else ""
            self._table.setItem(r, 0, QTableWidgetItem(t.name + suffix))
            self._table.setItem(r, 1, QTableWidgetItem(t.category))
            self._table.setItem(r, 2, QTableWidgetItem(format_bdt(t.default_price_paisa)))
            self._table.setItem(r, 3, QTableWidgetItem(str(t.usage_count)))
            cell = QWidget(self._table)
            h = QHBoxLayout(cell)
            h.setContentsMargins(Spacing.S1, Spacing.S1, Spacing.S1, Spacing.S1)
            h.setSpacing(Spacing.S1)
            edit = QPushButton("Edit", cell)
            from dentiva.core.permissions import Permission
            edit.setEnabled(self._principal.has(Permission.TREATMENTS_CATALOG_MANAGE))
            edit.clicked.connect(lambda _=False, tid=t.id: self._on_edit(tid))
            h.addWidget(edit)
            self._table.setCellWidget(r, 4, cell)

    def _on_new(self) -> None:
        if TreatmentCatalogDialog(
            self._session_factory, self._principal, parent=self
        ).exec():
            self._reload()

    def _on_edit(self, tid: int) -> None:
        if TreatmentCatalogDialog(
            self._session_factory, self._principal, catalog_id=tid, parent=self
        ).exec():
            self._reload()
