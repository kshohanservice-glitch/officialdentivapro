"""Invoices list view — all invoices with filters and quick actions."""
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from dentiva.core.dates import combine, format_datetime
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import invoice_service
from dentiva.ui.design_tokens import Spacing
from dentiva.ui.dialogs.invoice_dialog import InvoiceDialog
from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:

    from dentiva.core.permissions import Principal


STATUS_COLOR = {
    "draft": "#B54708", "unpaid": "#B42318", "partial": "#B54708",
    "paid": "#027A48", "void": "#667085",
}


class InvoicesView(QWidget):
    def __init__(self, session_factory, principal: Principal, parent=None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.S4)
        title=QLabel("Invoices",self)
        title.setObjectName("DpPageTitle")
        sub = QLabel(
            "Draft → Post (immutable). Track partial payments, print chits, void with reason.", self)
        sub.setObjectName("DpPageSubtitle")
        root.addWidget(title)
        root.addWidget(sub)

        bar=QHBoxLayout()
        bar.setSpacing(Spacing.S2)
        self._search=QLineEdit(self)
        self._search.setPlaceholderText("Search by patient or invoice number…")
        self._search.textChanged.connect(lambda _t: self._reload())
        bar.addWidget(self._search, 1)
        self._status = QComboBox(self)
        self._status.addItem("All statuses", None)
        for s in ("draft", "unpaid", "partial", "paid", "void"):
            self._status.addItem(s.title(), s)
        self._status.currentIndexChanged.connect(lambda _i: self._reload())
        bar.addWidget(self._status)
        self._from = QDateEdit(QDate.currentDate().addDays(-30), self)
        self._from.setCalendarPopup(True)
        self._from.setDisplayFormat("yyyy-MM-dd")
        self._from.dateChanged.connect(lambda _q: self._reload())
        self._to = QDateEdit(QDate.currentDate(), self)
        self._to.setCalendarPopup(True)
        self._to.setDisplayFormat("yyyy-MM-dd")
        self._to.dateChanged.connect(lambda _q: self._reload())
        bar.addWidget(QLabel("From"))
        bar.addWidget(self._from)
        bar.addWidget(QLabel("To"))
        bar.addWidget(self._to)
        root.addLayout(bar)

        self._table=QTableWidget(0,7,self)
        self._table.setObjectName("DpDataTable")
        self._table.setHorizontalHeaderLabels(
            ["#", "Date", "Patient", "Total", "Paid", "Due", "Status"])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.doubleClicked.connect(lambda _i: self._open_selected())
        self._table.verticalHeader().setVisible(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        for c in (3, 4, 5):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        root.addWidget(self._table, 1)
        self._reload()

    def refresh(self) -> None:
        self._reload()

    def _reload(self) -> None:
        from dentiva.core.money import format_bdt
        search = self._search.text().strip().lower() or None
        status = self._status.currentData()
        fd=self._from.date()
        td=self._to.date()
        start = combine(dt.date(fd.year(), fd.month(), fd.day()), dt.time(0, 0))
        end = combine(dt.date(td.year(), td.month(), td.day()), dt.time(23, 59, 59))
        with UnitOfWork(self._session_factory) as uow:
            invs = invoice_service.list_invoices(
                uow.session, self._principal,
                status=status, start=start, end=end, limit=500,
            )
        if search:
            invs = [i for i in invs if (search in i.patient_name.lower() or search in i.invoice_number.lower())]
        self._table.setRowCount(0)
        for inv in invs:
            r=self._table.rowCount()
            self._table.insertRow(r)
            self._table.setItem(r, 0, QTableWidgetItem(inv.invoice_number))
            self._table.setItem(r, 1, QTableWidgetItem(format_datetime(inv.date)))
            self._table.setItem(r, 2, QTableWidgetItem(inv.patient_name))
            self._table.setItem(r, 3, QTableWidgetItem(format_bdt(inv.total_paisa)))
            self._table.setItem(r, 4, QTableWidgetItem(format_bdt(inv.paid_paisa)))
            due_item = QTableWidgetItem(format_bdt(inv.due_paisa))
            if inv.due_paisa > 0 and inv.status in ("unpaid", "partial"):
                due_item.setForeground(QColor("#B42318"))
            self._table.setItem(r, 5, due_item)
            s = QTableWidgetItem(inv.status.title())
            s.setForeground(QColor(STATUS_COLOR.get(inv.status, "#475467")))
            self._table.setItem(r, 6, s)
            self._table.item(r, 0).setData(Qt.UserRole, inv.id)

    def _selected_id(self) -> int | None:
        r = self._table.currentRow()
        if r < 0:
            return None

        it = self._table.item(r, 0)
        v = it.data(Qt.UserRole) if it is not None else None
        return int(v) if isinstance(v, int) else None

    def _open_selected(self) -> None:
        iid = self._selected_id()
        if iid is None:
            return

        with UnitOfWork(self._session_factory) as uow:
            inv = invoice_service.get_invoice(uow.session, self._principal, iid)
            pid = inv.patient_id
            from dentiva.models import Patient
            pat = uow.session.get(Patient, pid)
        if pat is None:
            return

        if InvoiceDialog(self._session_factory, self._principal, pat, invoice=inv, parent=self).exec():

            self._reload()
