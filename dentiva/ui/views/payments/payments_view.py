"""Payments list view — payments across all invoices with date/method filters."""
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from dentiva.core.dates import combine, format_datetime
from dentiva.core.money import format_bdt
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import payment_service
from dentiva.ui.design_tokens import Spacing
from PySide6.QtCore import QDate
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


class PaymentsView(QWidget):
    def __init__(self, session_factory, principal: Principal, parent=None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.S4)
        title = QLabel("Payments", self)
        title.setObjectName("DpPageTitle")
        sub = QLabel(
            "All payments across invoices. Reverse/refund with reason for audit trail.",
            self,
        )
        sub.setObjectName("DpPageSubtitle")
        root.addWidget(title)
        root.addWidget(sub)

        bar = QHBoxLayout()
        bar.setSpacing(Spacing.S2)
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Search by patient / invoice # / reference…")
        self._search.textChanged.connect(lambda _t: self._reload())
        bar.addWidget(self._search, 1)
        self._method = QComboBox(self)
        self._method.addItem("All methods", None)
        with UnitOfWork(self._session_factory) as uow:
            for m in payment_service.list_payment_methods(uow.session, active_only=False):
                self._method.addItem(m.name, m.id)
        self._method.currentIndexChanged.connect(lambda _i: self._reload())
        bar.addWidget(self._method)
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

        self._table = QTableWidget(0, 6, self)
        self._table.setObjectName("DpDataTable")
        self._table.setHorizontalHeaderLabels(
            ["Date", "Patient", "Invoice", "Method", "Amount", "Reference"]
        )
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        root.addWidget(self._table, 1)
        self._reload()

    def refresh(self) -> None:
        self._reload()

    def _reload(self) -> None:
        search = self._search.text().strip().lower() or None
        fd = self._from.date()
        td = self._to.date()
        start = combine(dt.date(fd.year(), fd.month(), fd.day()), dt.time(0, 0))
        end = combine(dt.date(td.year(), td.month(), td.day()), dt.time(23, 59, 59))
        with UnitOfWork(self._session_factory) as uow:
            pays = payment_service.list_payments(
                uow.session,
                self._principal,
                method_id=self._method.currentData(),
                start=start,
                end=end,
                include_reversed=True,
                limit=500,
            )
        if search:
            pays = [
                p
                for p in pays
                if (
                    search in p.patient_name.lower()
                    or search in p.invoice_number.lower()
                    or (p.reference_no and search in p.reference_no.lower())
                )
            ]
        self._table.setRowCount(0)
        for p in pays:
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setItem(r, 0, QTableWidgetItem(format_datetime(p.paid_at)))
            self._table.setItem(r, 1, QTableWidgetItem(p.patient_name))
            self._table.setItem(r, 2, QTableWidgetItem(p.invoice_number))
            self._table.setItem(r, 3, QTableWidgetItem(p.method_name))
            amt = QTableWidgetItem(format_bdt(p.amount_paisa))
            ref = p.reference_no
            if p.reversed_at:
                amt.setForeground(QColor("#98A2B3"))
                amt.setText(amt.text() + " (reversed)")
                ref = ((ref + " · reversed: " + p.reversal_reason) if ref else "reversed: " + p.reversal_reason).strip()
            self._table.setItem(r, 4, amt)
            self._table.setItem(r, 5, QTableWidgetItem(ref))
