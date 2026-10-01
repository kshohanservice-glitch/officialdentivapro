# mypy: disable-error-code="arg-type, attr-defined, union-attr"
"""Accounting view — dashboard (period summary), entries ledger, categories."""
from __future__ import annotations

import calendar
import datetime as dt
from typing import TYPE_CHECKING

from dentiva.core.errors import DentivaError, ValidationError
from dentiva.core.money import format_bdt
from dentiva.core.permissions import Permission
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import accounting_service
from dentiva.ui.design_tokens import Spacing
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
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
    pass


class EntryDialog(QDialog):
    def __init__(self, session_factory, principal, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        self.setWindowTitle("New manual entry")
        self.setMinimumWidth(440)
        self.setModal(True)
        f = QFormLayout(self)

        self._date = QDateEdit(self)
        self._date.setCalendarPopup(True)
        self._date.setDate(dt.date.today())
        self._date.setDisplayFormat("dd MMM yyyy")
        self._kind = QComboBox(self)
        self._kind.addItem("Expense", "expense")
        self._kind.addItem("Income", "income")
        self._kind.currentIndexChanged.connect(self._reload_categories)
        self._category = QComboBox(self)
        self._amount = QSpinBox(self)
        self._amount.setRange(1, 10_000_000)
        self._amount.setSuffix(" ৳")
        self._amount.setSingleStep(100)
        self._method = QComboBox(self)
        self._method.addItem("(none)", None)
        self._ref = QLineEdit(self)
        self._ref.setPlaceholderText("Receipt #, memo, …")
        self._desc = QLineEdit(self)
        self._desc.setPlaceholderText("Description (optional)")

        with UnitOfWork(session_factory) as uow:
            accounting_service.ensure_default_categories(uow.session)
            from dentiva.models import PaymentMethod
            from sqlalchemy import select
            q = select(PaymentMethod).where(PaymentMethod.is_active.is_(True)).order_by(PaymentMethod.name)
            for pm in uow.session.scalars(q):
                self._method.addItem(pm.name, pm.id)

        f.addRow("Date", self._date)
        f.addRow("Type", self._kind)
        f.addRow("Category *", self._category)
        f.addRow("Amount *", self._amount)
        f.addRow("Payment method", self._method)
        f.addRow("Reference", self._ref)
        f.addRow("Description", self._desc)
        self._err = QLabel("", self)
        self._err.setObjectName("DpFieldError")
        self._err.setWordWrap(True)
        f.addRow(self._err)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self._reload_categories()

    def _reload_categories(self) -> None:
        kind = self._kind.currentData()
        self._category.clear()
        with UnitOfWork(self._sf) as uow:
            cats = accounting_service.list_categories(uow.session, self._p, kind=kind, active_only=True)
        for c in cats:
            self._category.addItem(c.name, c.id)

    def _save(self) -> None:
        self._err.setText("")
        qd = self._date.date()
        date = dt.date(qd.year(), qd.month(), qd.day())
        data = accounting_service.EntryInput(
            date=date,
            kind=self._kind.currentData(),
            category_id=self._category.currentData(),
            amount_paisa=int(self._amount.value()) * 100,
            payment_method_id=self._method.currentData(),
            reference=self._ref.text().strip(),
            description=self._desc.text().strip(),
        )
        try:
            with UnitOfWork(self._sf) as uow:
                accounting_service.create_entry(uow.session, self._p, data)
                uow.commit()
        except ValidationError as e:
            self._err.setText(e.user_message)
            return
        except DentivaError as e:
            self._err.setText(e.user_message)
            return
        self.accept()


class CategoryDialog(QDialog):
    def __init__(self, session_factory, principal, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        self.setWindowTitle("New category")
        self.setMinimumWidth(400)
        self.setModal(True)
        f = QFormLayout(self)
        self._kind = QComboBox(self)
        self._kind.addItem("Expense", "expense")
        self._kind.addItem("Income", "income")
        self._name = QLineEdit(self)
        self._name.setPlaceholderText("Category name")
        self._parent = QComboBox(self)
        self._parent.addItem("(top-level)", None)
        f.addRow("Type", self._kind)
        f.addRow("Name *", self._name)
        f.addRow("Parent", self._parent)
        self._kind.currentIndexChanged.connect(self._reload_parents)
        self._err = QLabel("", self)
        self._err.setObjectName("DpFieldError")
        self._err.setWordWrap(True)
        f.addRow(self._err)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self._reload_parents()

    def _reload_parents(self) -> None:
        self._parent.clear()
        self._parent.addItem("(top-level)", None)
        with UnitOfWork(self._sf) as uow:
            cats = accounting_service.list_categories(uow.session, self._p, kind=self._kind.currentData())
        for c in cats:
            self._parent.addItem(c.name, c.id)

    def _save(self) -> None:
        self._err.setText("")
        data = accounting_service.CategoryInput(
            name=self._name.text().strip(),
            kind=self._kind.currentData(),
            parent_id=self._parent.currentData(),
        )
        try:
            with UnitOfWork(self._sf) as uow:
                accounting_service.create_category(uow.session, self._p, data)
                uow.commit()
        except ValidationError as e:
            self._err.setText(e.user_message)
            return
        except DentivaError as e:
            self._err.setText(e.user_message)
            return
        self.accept()


def _last_month_range(today: dt.date) -> tuple[dt.date, dt.date]:
    if today.month == 1:
        y, m = today.year - 1, 12
    else:
        y, m = today.year, today.month - 1
    last_day = calendar.monthrange(y, m)[1]
    return dt.date(y, m, 1), dt.date(y, m, last_day)


def _quick_periods(today: dt.date) -> list[tuple[str, dt.date, dt.date]]:
    lm_start, lm_end = _last_month_range(today)
    return [
        ("Today", today, today),
        ("Last 7 days", today - dt.timedelta(days=6), today),
        ("This month", today.replace(day=1), today),
        ("Last month", lm_start, lm_end),
        ("This year", today.replace(month=1, day=1), today),
        ("All time", dt.date(2000, 1, 1), today),
    ]


class AccountingView(QWidget):
    def __init__(self, session_factory, principal, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        self._start: dt.date = dt.date.today().replace(day=1)
        self._end: dt.date = dt.date.today()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.S4)

        title = QLabel("Accounting", self)
        title.setObjectName("DpPageTitle")
        sub_text = (
            "Income, expenses and profitability. Payments are posted automatically; "
            "you can add manual income/expense entries here."
        )
        sub = QLabel(sub_text, self)
        sub.setObjectName("DpPageSubtitle")
        root.addWidget(title)
        root.addWidget(sub)

        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_dashboard_tab(), "Dashboard")
        self._tabs.addTab(self._build_ledger_tab(), "Ledger entries")
        self._tabs.addTab(self._build_categories_tab(), "Categories")
        self._tabs.currentChanged.connect(lambda _i: self._reload_active())
        root.addWidget(self._tabs, 1)

    def refresh(self) -> None:
        self._reload_active()

    def _reload_active(self) -> None:
        idx = self._tabs.currentIndex()
        if idx == 0:
            self._reload_dashboard()
        elif idx == 1:
            self._reload_ledger()
        elif idx == 2:
            self._reload_categories()

    # ---- Dashboard
    def _build_dashboard_tab(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.S3)

        bar = QHBoxLayout()
        bar.setSpacing(Spacing.S2)
        self._period_combo = QComboBox(w)
        for label, s, e in _quick_periods(dt.date.today()):
            self._period_combo.addItem(label, (s, e))
        self._period_combo.setCurrentIndex(2)
        self._period_combo.currentIndexChanged.connect(self._on_period_change)

        self._start_d = QDateEdit(w)
        self._start_d.setCalendarPopup(True)
        self._start_d.setDisplayFormat("dd MMM yyyy")
        self._end_d = QDateEdit(w)
        self._end_d.setCalendarPopup(True)
        self._end_d.setDisplayFormat("dd MMM yyyy")
        self._start_d.setDate(self._start)
        self._end_d.setDate(self._end)
        self._start_d.dateChanged.connect(lambda _q: self._apply_custom())
        self._end_d.dateChanged.connect(lambda _q: self._apply_custom())

        refresh_btn = QPushButton("Refresh", w)
        refresh_btn.clicked.connect(self._reload_dashboard)
        self._new_btn = QPushButton("+ New entry", w)
        self._new_btn.setProperty("variant", "primary")
        self._new_btn.clicked.connect(self._on_new_entry)
        from dentiva.core.permissions import Permission
        self._new_btn.setVisible(self._p.has(Permission.ACCOUNTING_MANAGE))

        bar.addWidget(QLabel("Period:", w))
        bar.addWidget(self._period_combo)
        bar.addSpacing(8)
        bar.addWidget(QLabel("From", w))
        bar.addWidget(self._start_d)
        bar.addWidget(QLabel("to", w))
        bar.addWidget(self._end_d)
        bar.addWidget(refresh_btn)
        bar.addStretch(1)
        bar.addWidget(self._new_btn)
        lay.addLayout(bar)

        self._kpi_grid = QGridLayout()
        self._kpi_grid.setSpacing(Spacing.S3)
        self._tiles: dict[str, QLabel] = {}

        def add_tile(key: str, title: str, col: int) -> None:
            box = QWidget(w)
            box.setObjectName("DpCard")
            vb = QVBoxLayout(box)
            vb.setContentsMargins(14, 10, 14, 10)
            t = QLabel(title, box)
            t.setObjectName("DpCardLabel")
            v = QLabel("—", box)
            v.setObjectName("DpCardValue")
            vb.addWidget(t)
            vb.addWidget(v)
            self._kpi_grid.addWidget(box, 0, col)
            self._tiles[key] = v

        for col, key_title in enumerate([
            ("income", "Income"),
            ("expense", "Expenses"),
            ("profit", "Net profit"),
            ("billed", "Billed (invoices)"),
            ("collected", "Collected (payments)"),
        ]):
            add_tile(key_title[0], key_title[1], col)
        lay.addLayout(self._kpi_grid)

        self._inc_tbl = self._kv_table(w, ["Income by category", "৳"])
        self._exp_tbl = self._kv_table(w, ["Expense by category", "৳"])
        self._method_tbl = self._kv_table(w, ["Income by payment method", "৳"])

        self._daily_tbl = QTableWidget(0, 4, w)
        self._daily_tbl.setObjectName("DpDataTable")
        self._daily_tbl.setHorizontalHeaderLabels(["Date", "Income", "Expense", "Net"])
        self._daily_tbl.setEditTriggers(self._daily_tbl.EditTrigger(0))
        self._daily_tbl.verticalHeader().setVisible(False)
        dhh = self._daily_tbl.horizontalHeader()
        dhh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for c in (1, 2, 3):
            dhh.setSectionResizeMode(c, QHeaderView.Stretch)

        split = QHBoxLayout()
        for caption, tbl in [
            ("Income by category", self._inc_tbl),
            ("Expenses by category", self._exp_tbl),
            ("Collected by method", self._method_tbl),
        ]:
            wrap = QVBoxLayout()
            cap = QLabel(caption, w)
            cap.setObjectName("DpSectionTitle")
            wrap.addWidget(cap)
            wrap.addWidget(tbl, 1)
            split.addLayout(wrap, 1)
        lay.addLayout(split, 1)
        daily_title = QLabel("Daily trend", w)
        daily_title.setObjectName("DpSectionTitle")
        lay.addWidget(daily_title)
        lay.addWidget(self._daily_tbl)
        self._reload_dashboard()
        return w

    def _kv_table(self, parent: QWidget, headers: list[str]) -> QTableWidget:
        t = QTableWidget(0, len(headers), parent)
        t.setObjectName("DpDataTable")
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(t.EditTrigger(0))
        t.verticalHeader().setVisible(False)
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        return t

    def _on_period_change(self, _i: int) -> None:
        data = self._period_combo.currentData()
        if data is None:
            return
        s, e = data
        self._start = s
        self._end = e
        self._start_d.blockSignals(True)
        self._end_d.blockSignals(True)
        self._start_d.setDate(s)
        self._end_d.setDate(e)
        self._start_d.blockSignals(False)
        self._end_d.blockSignals(False)
        self._reload_dashboard()

    def _apply_custom(self) -> None:
        qs = self._start_d.date()
        qe = self._end_d.date()
        self._start = dt.date(qs.year(), qs.month(), qs.day())
        self._end = dt.date(qe.year(), qe.month(), qe.day())
        self._period_combo.blockSignals(True)
        self._period_combo.setCurrentIndex(self._period_combo.count() - 1)
        self._period_combo.blockSignals(False)
        self._reload_dashboard()

    def _reload_dashboard(self) -> None:
        try:
            with UnitOfWork(self._sf) as uow:
                totals = accounting_service.period_totals(
                    uow.session, self._p, start=self._start, end=self._end
                )
        except DentivaError:
            return
        self._tiles["income"].setText(format_bdt(totals.income_paisa))
        self._tiles["expense"].setText(format_bdt(totals.expense_paisa))
        profit = totals.profit_paisa
        self._tiles["profit"].setText(format_bdt(profit))
        if profit < 0:
            self._tiles["profit"].setStyleSheet("color: #c0392b;")
        else:
            self._tiles["profit"].setStyleSheet("")
        self._tiles["billed"].setText(format_bdt(totals.receivable_added_paisa))
        self._tiles["collected"].setText(format_bdt(totals.receivable_paid_paisa))
        self._fill_kv(self._inc_tbl, totals.by_category_income)
        self._fill_kv(self._exp_tbl, totals.by_category_expense)
        self._fill_kv(self._method_tbl, totals.by_method_income)
        self._daily_tbl.setRowCount(0)
        for d, inc, exp, net in totals.daily_net:
            r = self._daily_tbl.rowCount()
            self._daily_tbl.insertRow(r)
            self._daily_tbl.setItem(r, 0, QTableWidgetItem(d.strftime("%d %b %Y")))
            self._daily_tbl.setItem(r, 1, QTableWidgetItem(format_bdt(inc)))
            self._daily_tbl.setItem(r, 2, QTableWidgetItem(format_bdt(exp)))
            ni = QTableWidgetItem(format_bdt(net))
            if net < 0:
                ni.setForeground(Qt.GlobalColor.red)
            self._daily_tbl.setItem(r, 3, ni)

    def _fill_kv(self, table: QTableWidget, rows: list[tuple[str, int]]) -> None:
        table.setRowCount(0)
        if not rows:
            r = table.rowCount()
            table.insertRow(r)
            it = QTableWidgetItem("(no entries)")
            it.setForeground(Qt.GlobalColor.gray)
            table.setItem(r, 0, it)
            table.setItem(r, 1, QTableWidgetItem(""))
            return
        for label, paisa in rows:
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QTableWidgetItem(label))
            table.setItem(r, 1, QTableWidgetItem(format_bdt(paisa)))

    # ---- Ledger
    def _build_ledger_tab(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.S3)
        bar = QHBoxLayout()

        self._ledger_start = QDateEdit(w)
        self._ledger_start.setCalendarPopup(True)
        self._ledger_start.setDisplayFormat("dd MMM yyyy")
        self._ledger_end = QDateEdit(w)
        self._ledger_end.setCalendarPopup(True)
        self._ledger_end.setDisplayFormat("dd MMM yyyy")
        today = dt.date.today()
        self._ledger_start.setDate(today - dt.timedelta(days=30))
        self._ledger_end.setDate(today)
        self._ledger_kind = QComboBox(w)
        self._ledger_kind.addItem("All", None)
        self._ledger_kind.addItem("Income", "income")
        self._ledger_kind.addItem("Expense", "expense")
        go = QPushButton("Apply filter", w)
        go.clicked.connect(self._reload_ledger)
        new_btn = QPushButton("+ New entry", w)
        new_btn.setProperty("variant", "primary")
        new_btn.clicked.connect(self._on_new_entry)
        new_btn.setVisible(self._p.has(Permission.ACCOUNTING_MANAGE))

        bar.addWidget(QLabel("From", w))
        bar.addWidget(self._ledger_start)
        bar.addWidget(QLabel("to", w))
        bar.addWidget(self._ledger_end)
        bar.addWidget(QLabel("Type", w))
        bar.addWidget(self._ledger_kind)
        bar.addWidget(go)
        bar.addStretch(1)
        bar.addWidget(new_btn)
        lay.addLayout(bar)

        self._ledger_tbl = QTableWidget(0, 7, w)
        self._ledger_tbl.setObjectName("DpDataTable")
        self._ledger_tbl.setHorizontalHeaderLabels(
            ["Date", "Type", "Category", "Amount", "Method", "Description/Reference", "Source"]
        )
        self._ledger_tbl.setEditTriggers(self._ledger_tbl.EditTrigger(0))
        self._ledger_tbl.verticalHeader().setVisible(False)
        hh = self._ledger_tbl.horizontalHeader()
        for c, mode in enumerate([
            QHeaderView.ResizeToContents, QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents, QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents, QHeaderView.Stretch,
            QHeaderView.ResizeToContents,
        ]):
            hh.setSectionResizeMode(c, mode)
        lay.addWidget(self._ledger_tbl, 1)
        return w

    def _reload_ledger(self) -> None:
        qs = self._ledger_start.date()
        qe = self._ledger_end.date()
        start = dt.date(qs.year(), qs.month(), qs.day())
        end = dt.date(qe.year(), qe.month(), qe.day())
        kind = self._ledger_kind.currentData()
        try:
            with UnitOfWork(self._sf) as uow:
                entries = accounting_service.list_entries(
                    uow.session, self._p, start=start, end=end, kind=kind, limit=1000
                )
        except DentivaError:
            return
        self._ledger_tbl.setRowCount(0)
        source_label = {
            "manual": "Manual",
            "payment": "Payment",
            "payment_reversal": "Refund",
        }
        for e in entries:
            r = self._ledger_tbl.rowCount()
            self._ledger_tbl.insertRow(r)
            self._ledger_tbl.setItem(r, 0, QTableWidgetItem(e.date.strftime("%d %b %Y")))
            type_text = e.kind.title()
            color = None
            if e.kind == "income" and e.signed_paisa < 0:
                type_text = "Refund"
                color = Qt.GlobalColor.darkRed
            elif e.kind == "income":
                color = Qt.GlobalColor.darkGreen
            ti = QTableWidgetItem(type_text)
            if color is not None:
                ti.setForeground(color)
            self._ledger_tbl.setItem(r, 1, ti)
            self._ledger_tbl.setItem(r, 2, QTableWidgetItem(e.category_name))
            amt = QTableWidgetItem(format_bdt(abs(e.amount_paisa)))
            amt.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._ledger_tbl.setItem(r, 3, amt)
            self._ledger_tbl.setItem(r, 4, QTableWidgetItem(e.payment_method))
            desc = e.description or e.reference
            self._ledger_tbl.setItem(r, 5, QTableWidgetItem(desc))
            self._ledger_tbl.setItem(r, 6, QTableWidgetItem(source_label.get(e.source, e.source)))

    # ---- Categories
    def _build_categories_tab(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(Spacing.S3)
        bar = QHBoxLayout()
        info = QLabel(
            "Default categories are created automatically on setup. You can add more here.", w
        )
        info.setObjectName("DpMutedLabel")
        new_btn = QPushButton("+ New category", w)
        new_btn.setProperty("variant", "primary")
        new_btn.clicked.connect(self._on_new_category)
        new_btn.setVisible(self._p.has(Permission.ACCOUNTING_MANAGE))
        bar.addWidget(info, 1)
        bar.addWidget(new_btn)
        lay.addLayout(bar)

        self._cat_tbl = QTableWidget(0, 3, w)
        self._cat_tbl.setObjectName("DpDataTable")
        self._cat_tbl.setHorizontalHeaderLabels(["Type", "Name", "Parent"])
        self._cat_tbl.setEditTriggers(self._cat_tbl.EditTrigger(0))
        self._cat_tbl.verticalHeader().setVisible(False)
        hh = self._cat_tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        lay.addWidget(self._cat_tbl, 1)
        return w

    def _reload_categories(self) -> None:
        try:
            with UnitOfWork(self._sf) as uow:
                cats = accounting_service.list_categories(uow.session, self._p)
        except DentivaError:
            return
        self._cat_tbl.setRowCount(0)
        for c in cats:
            r = self._cat_tbl.rowCount()
            self._cat_tbl.insertRow(r)
            self._cat_tbl.setItem(r, 0, QTableWidgetItem(c.kind.title()))
            suffix = "" if c.is_active else "  (inactive)"
            self._cat_tbl.setItem(r, 1, QTableWidgetItem(c.name + suffix))
            self._cat_tbl.setItem(r, 2, QTableWidgetItem(c.parent_name or "(top-level)"))

    # ---- Actions
    def _on_new_entry(self) -> None:
        if EntryDialog(self._sf, self._p, parent=self).exec():
            self._reload_dashboard()
            self._reload_ledger()

    def _on_new_category(self) -> None:
        if CategoryDialog(self._sf, self._p, parent=self).exec():
            self._reload_categories()
