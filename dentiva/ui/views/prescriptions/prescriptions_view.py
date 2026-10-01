"""Prescriptions list view — browse all prescriptions, open to edit/print."""
from __future__ import annotations

from typing import TYPE_CHECKING

from dentiva.core.dates import format_datetime
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import prescription_service
from dentiva.ui.design_tokens import Spacing
from dentiva.ui.dialogs.prescription_dialog import PrescriptionDialog
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from dentiva.core.permissions import Principal


class PrescriptionsView(QWidget):
    def __init__(self, session_factory, principal: Principal, parent=None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.S4)

        title = QLabel("Prescriptions", self)
        title.setObjectName("DpPageTitle")
        sub = QLabel(
            "Browse finalized and draft prescriptions. Finalized prescriptions are locked and print-ready.",
            self,
        )
        sub.setObjectName("DpPageSubtitle")
        root.addWidget(title)
        root.addWidget(sub)

        bar = QHBoxLayout()
        bar.setSpacing(Spacing.S2)
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Search by patient name…")
        self._search.textChanged.connect(lambda _t: self._reload())
        bar.addWidget(self._search, 1)
        self._finalized = QCheckBox("Finalized only", self)
        self._finalized.toggled.connect(lambda _: self._reload())
        bar.addWidget(self._finalized)
        self._drafts = QCheckBox("Drafts only", self)
        self._drafts.toggled.connect(lambda _: self._reload())
        bar.addWidget(self._drafts)
        self._new_btn = QPushButton("+ New prescription", self)
        self._new_btn.setProperty("variant", "primary")
        self._new_btn.clicked.connect(self._on_new)
        self._new_btn.setVisible(self._principal.has(__import__("dentiva.core.permissions", fromlist=["Permission"]).Permission.PRESCRIPTIONS_CREATE))
        bar.addWidget(self._new_btn)
        root.addLayout(bar)

        self._table = QTableWidget(0, 5, self)
        self._table.setObjectName("DpDataTable")
        self._table.setHorizontalHeaderLabels(["Date", "Patient", "Dentist", "Medicines", "Status"])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.doubleClicked.connect(lambda _i: self._open_selected())
        self._table.verticalHeader().setVisible(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        root.addWidget(self._table, 1)
        self._reload()

    def refresh(self) -> None:
        self._reload()

    def _reload(self) -> None:
        search = (self._search.text().strip().lower()) or None
        finalized = None
        if self._finalized.isChecked() and not self._drafts.isChecked():
            finalized = True
        elif self._drafts.isChecked() and not self._finalized.isChecked():
            finalized = False
        with UnitOfWork(self._session_factory) as uow:
            rxs = prescription_service.list_prescriptions(
                uow.session, self._principal, finalized=finalized, limit=500
            )
        if search:
            rxs = [r for r in rxs if search in r.patient_name.lower()]
        self._table.setRowCount(0)
        for rx in rxs:
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setItem(r, 0, QTableWidgetItem(format_datetime(rx.date)))
            self._table.setItem(r, 1, QTableWidgetItem(rx.patient_name))
            self._table.setItem(r, 2, QTableWidgetItem(rx.dentist_name))
            self._table.setItem(r, 3, QTableWidgetItem(str(len(rx.medicines))))
            status = QTableWidgetItem("Finalized" if rx.finalized else "Draft")
            status.setForeground(QColor("#027A48" if rx.finalized else "#B54708"))
            self._table.setItem(r, 4, status)
            self._table.item(r, 0).setData(Qt.UserRole, rx.id)

    def _selected_id(self) -> int | None:
        r = self._table.currentRow()
        if r < 0:
            return None
        it = self._table.item(r, 0)
        if it is None:
            return None
        v = it.data(Qt.UserRole)
        return int(v) if isinstance(v, int) else None

    def _open_selected(self) -> None:
        rid = self._selected_id()
        if rid is None:
            return
        with UnitOfWork(self._session_factory) as uow:
            rx = prescription_service.get_prescription(uow.session, self._principal, rid)
        if PrescriptionDialog(
            self._session_factory, self._principal, prescription=rx, parent=self
        ).exec():
            self._reload()

    def _on_new(self) -> None:
        if PrescriptionDialog(self._session_factory, self._principal, parent=self).exec():
            self._reload()
