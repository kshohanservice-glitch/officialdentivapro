"""Invoice dialog — create/edit draft invoice, add lines, post, record payment."""
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from dentiva.core.dates import format_datetime, local_now
from dentiva.core.errors import DentivaError, ValidationError
from dentiva.core.money import format_bdt, parse_bdt
from dentiva.core.permissions import Permission
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.models import Patient
from dentiva.services import invoice_service, payment_service, treatment_service
from dentiva.ui.design_tokens import Spacing

if TYPE_CHECKING:

    from dentiva.core.permissions import Principal


class _LineEditor(QWidget):
    """Single line row inside the invoice lines table. Delegates signals upward."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)


class InvoiceDialog(QDialog):
    def __init__(
        self,
        session_factory,
        principal: Principal,
        patient: Patient,
        *,
        invoice=None,  # InvoiceRow or None
        visit_id: int | None = None,
        from_visit_treatments: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal
        self._patient = patient
        self._invoice = invoice
        self._invoice_id: int | None = invoice.id if invoice else None
        self._visit_id = visit_id or (invoice.visit_id if invoice else None)
        self.setMinimumSize(900, 640)
        self.setWindowTitle(f"{'Edit' if invoice else 'New'} invoice — {patient.name}")
        self.setModal(True)

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        title = QLabel(self.windowTitle(), self)
        title.setObjectName("DpPageTitle")
        top.addWidget(title)
        top.addStretch(1)
        self._number_lbl = QLabel("", self)
        self._status_lbl = QLabel("", self)
        self._status_lbl.setStyleSheet("font-weight:600;")
        top.addWidget(self._number_lbl)
        top.addWidget(self._status_lbl)
        root.addLayout(top)

        # Tabs: Lines / Payments
        self._tabs = QTabWidget(self)
        lines_tab = QWidget(self)
        self._build_lines_tab(lines_tab)
        self._tabs.addTab(lines_tab, "Line items")
        pay_tab = QWidget(self)
        self._build_payments_tab(pay_tab)
        self._tabs.addTab(pay_tab, "Payments")
        root.addWidget(self._tabs, 1)

        # Totals bar
        totals = QHBoxLayout()
        totals.addStretch(1)
        self._sub_lbl = QLabel("Subtotal: ৳0.00", self)
        self._disc_lbl = QLabel("Discount: ৳0.00", self)
        self._tax_lbl = QLabel("Tax: ৳0.00", self)
        self._tot_lbl = QLabel("TOTAL: ৳0.00", self)
        self._tot_lbl.setStyleSheet("font-size:15px; font-weight:700;")
        self._paid_lbl = QLabel("Paid: ৳0.00", self)
        self._due_lbl = QLabel("Due: ৳0.00", self)
        self._due_lbl.setStyleSheet("color:#B42318; font-weight:600;")
        for w in (self._sub_lbl, self._disc_lbl, self._tax_lbl, self._tot_lbl, self._paid_lbl, self._due_lbl):
            totals.addSpacing(Spacing.S4)
            totals.addWidget(w)
        root.addLayout(totals)

        self._error = QLabel("", self)
        self._error.setObjectName("DpFieldError")
        self._error.setWordWrap(True)
        root.addWidget(self._error)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self._void_btn = QPushButton("Void", self)
        self._void_btn.setProperty("variant", "danger")
        self._void_btn.clicked.connect(self._on_void)
        self._void_btn.setVisible(False)
        self._print_btn = QPushButton("Print…", self)
        self._print_btn.clicked.connect(self._on_print)
        self._print_btn.setVisible(False)
        self._pdf_btn = QPushButton("PDF…", self)
        self._pdf_btn.clicked.connect(self._on_pdf)
        self._pdf_btn.setVisible(False)
        self._post_btn = QPushButton("Post & finalize", self)
        self._post_btn.setProperty("variant", "primary")
        self._post_btn.clicked.connect(self._on_post)
        self._save_btn = QPushButton("Save draft", self)
        self._save_btn.setProperty("variant", "primary-subtle")
        self._save_btn.clicked.connect(self._on_save_draft)
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)
        btns.addWidget(self._void_btn)
        btns.addWidget(self._print_btn)
        btns.addWidget(self._pdf_btn)
        btns.addWidget(close_btn)
        btns.addWidget(self._save_btn)
        btns.addWidget(self._post_btn)
        root.addLayout(btns)

        # If this is a new invoice and from_visit_treatments, auto-build lines
        # from visit treatment records.
        self._autobuild_from_visit = (
            invoice is None and from_visit_treatments and self._visit_id is not None
        )
        self._load()

    # ------------------------------------------------------ build
    def _build_lines_tab(self, w: QWidget) -> None:
        v = QVBoxLayout(w)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self._date = QDateTimeEdit(w)
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("yyyy-MM-dd HH:mm")
        from PySide6.QtCore import QDateTime
        self._date.setDateTime(QDateTime.currentDateTime())
        form.addRow("Date", self._date)
        self._discount = QLineEdit("0", w)
        self._discount.setPlaceholderText("Discount in ৳")
        self._discount.setMaximumWidth(140)
        self._discount.textChanged.connect(lambda _t: self._recalc_totals_display())
        form.addRow("Discount", self._discount)
        self._tax = QLineEdit("0", w)
        self._tax.setPlaceholderText("Tax in ৳")
        self._tax.setMaximumWidth(140)
        self._tax.textChanged.connect(lambda _t: self._recalc_totals_display())
        form.addRow("Tax", self._tax)
        self._notes = QPlainTextEdit(w)
        self._notes.setFixedHeight(40)
        form.addRow("Notes", self._notes)
        v.addLayout(form)

        bar = QHBoxLayout()
        self._add_line_btn = QPushButton("+ Add line", w)
        self._add_line_btn.setProperty("variant", "primary")
        self._add_line_btn.clicked.connect(lambda: self._add_row())
        bar.addWidget(self._add_line_btn)
        self._from_visit_btn = QPushButton("Load from visit treatments", w)
        self._from_visit_btn.clicked.connect(self._on_load_from_visit)
        self._from_visit_btn.setEnabled(self._visit_id is not None)
        bar.addWidget(self._from_visit_btn)
        bar.addStretch(1)
        v.addLayout(bar)

        self._lines_table = QTableWidget(0, 6, w)
        self._lines_table.setObjectName("DpDataTable")
        self._lines_table.setHorizontalHeaderLabels(["Description", "Catalog/Ref", "Qty", "Unit price", "Line total", ""])
        self._lines_table.verticalHeader().setVisible(False)
        hh = self._lines_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        v.addWidget(self._lines_table, 1)

    def _build_payments_tab(self, w: QWidget) -> None:
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self._pay_method = QComboBox(w)
        self._pay_amount = QLineEdit(w)
        self._pay_amount.setPlaceholderText("Amount in ৳")
        self._pay_amount.setMaximumWidth(140)
        self._pay_ref = QLineEdit(w)
        self._pay_ref.setPlaceholderText("Reference/TrxID (optional)")
        self._pay_notes = QLineEdit(w)
        self._pay_notes.setPlaceholderText("Notes")
        self._add_pay_btn = QPushButton("Record payment", w)
        self._add_pay_btn.setProperty("variant", "primary")
        self._add_pay_btn.clicked.connect(self._on_record_payment)
        bar.addWidget(QLabel("Method:"))
        bar.addWidget(self._pay_method)
        bar.addWidget(QLabel("Amount:"))
        bar.addWidget(self._pay_amount)
        bar.addWidget(self._pay_ref)
        bar.addWidget(self._pay_notes, 1)
        bar.addWidget(self._add_pay_btn)
        v.addLayout(bar)
        self._pay_table = QTableWidget(0, 6, w)
        self._pay_table.setObjectName("DpDataTable")
        self._pay_table.setHorizontalHeaderLabels(["Date", "Method", "Amount", "Reference", "Notes", ""])
        self._pay_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._pay_table.verticalHeader().setVisible(False)
        hh = self._pay_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        v.addWidget(self._pay_table, 1)
        # Load payment methods
        with UnitOfWork(self._session_factory) as uow:
            for m in payment_service.list_payment_methods(uow.session):
                self._pay_method.addItem(m.name, m.id)

    # ------------------------------------------------------ load
    def _load(self) -> None:
        # If new invoice, optionally auto-load from visit
        if self._autobuild_from_visit:
            self._load_from_visit()
        if self._invoice is None:
            self._number_lbl.setText("")
            self._status_lbl.setText("Draft")
            self._status_lbl.setStyleSheet("color:#B54708; font-weight:600;")
            self._add_row()
            self._reload_payments()
            self._recalc_totals_display()
            return
        # Load existing invoice
        self._number_lbl.setText(f"<b>{self._invoice.invoice_number}</b>")
        self._set_status_style(self._invoice.status)
        from PySide6.QtCore import QDateTime
        self._date.setDateTime(QDateTime.fromString(
            self._invoice.date.strftime("%Y-%m-%d %H:%M"), "yyyy-MM-dd HH:mm"))
        self._discount.setText(str((self._invoice.discount_paisa or 0) // 100))
        self._tax.setText(str((self._invoice.tax_paisa or 0) // 100))
        self._notes.setPlainText(self._invoice.notes or "")
        self._lines_table.setRowCount(0)
        for ln in self._invoice.lines:
            self._add_row(desc=ln.description, qty=ln.quantity, price=ln.unit_price_paisa)
        self._reload_payments()
        self._recalc_totals_display()
        locked = self._invoice.is_posted
        for w in (self._discount, self._tax, self._notes, self._date,
                  self._add_line_btn, self._from_visit_btn, self._add_pay_btn, self._save_btn):
            w.setEnabled(not locked)
        self._post_btn.setEnabled(not locked and self._principal.has(Permission.INVOICES_EDIT))
        self._void_btn.setVisible(bool(self._invoice.is_posted) and self._principal.has(Permission.INVOICES_VOID))
        can_print = bool(self._invoice.is_posted) and self._principal.has(Permission.INVOICES_PRINT)
        self._print_btn.setVisible(can_print)
        self._pdf_btn.setVisible(can_print)

    def _set_status_style(self, status: str) -> None:
        colors = {"draft": "#B54708", "unpaid": "#B42318", "partial": "#B54708",
                  "paid": "#027A48", "void": "#667085"}
        labels = {"draft": "Draft", "unpaid": "Unpaid", "partial": "Partial",
                  "paid": "Paid", "void": "Voided"}
        self._status_lbl.setText(labels.get(status, status.title()))
        self._status_lbl.setStyleSheet(f"color:{colors.get(status, '#475467')}; font-weight:600;")

    # ------------------------------------------------------ lines UI
    def _add_row(self, *, desc="", qty=1, price=0) -> None:
        r = self._lines_table.rowCount()
        self._lines_table.insertRow(r)
        desc_w = QLineEdit(self._lines_table)
        desc_w.setPlaceholderText("Description")
        desc_w.setText(desc)
        desc_w.textChanged.connect(lambda _t: self._recalc_totals_display())
        self._lines_table.setCellWidget(r, 0, desc_w)
        ref = QComboBox(self._lines_table)
        ref.addItem("Custom", None)
        with UnitOfWork(self._session_factory) as uow:
            cats = treatment_service.list_catalog(uow.session, self._principal, active_only=True)
        for c in cats:
            ref.addItem(f"{c.name} ({format_bdt(c.default_price_paisa)})", c.id)
        self._lines_table.setCellWidget(r, 1, ref)
        qty_sb = QSpinBox(self._lines_table)
        qty_sb.setRange(1,100)
        qty_sb.setValue(qty)
        qty_sb.valueChanged.connect(lambda _v: self._recalc_totals_display())
        self._lines_table.setCellWidget(r, 2, qty_sb)
        price_w = QLineEdit(self._lines_table)
        price_w.setPlaceholderText("৳")
        if price:
            price_w.setText(str(price / 100))
        price_w.textChanged.connect(lambda _t: self._recalc_totals_display())
        self._lines_table.setCellWidget(r, 3, price_w)
        total_lbl = QLabel("৳0.00", self._lines_table)
        total_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._lines_table.setCellWidget(r, 4, total_lbl)
        rm = QPushButton("✕", self._lines_table)
        rm.setFixedWidth(28)
        rm.setProperty("variant", "danger-text")
        rm.clicked.connect(lambda _=False, row=r: self._remove_row(row))
        self._lines_table.setCellWidget(r, 5, rm)
        self._lines_table.setRowHeight(r, 34)

    def _remove_row(self, row: int) -> None:
        self._lines_table.removeRow(row)
        if self._lines_table.rowCount() == 0:
            self._add_row()
        self._recalc_totals_display()

    def _collect_lines(self) -> list[invoice_service.InvoiceLineInput]:
        lines: list[invoice_service.InvoiceLineInput] = []
        for r in range(self._lines_table.rowCount()):
            desc_w = self._lines_table.cellWidget(r, 0)
            desc = desc_w.text().strip() if isinstance(desc_w, QLineEdit) else ""
            if not desc:
                continue
            ref_cb = self._lines_table.cellWidget(r, 1)
            ref_id = ref_cb.currentData() if isinstance(ref_cb, QComboBox) else None
            qty_sb = self._lines_table.cellWidget(r, 2)
            qty = int(qty_sb.value()) if isinstance(qty_sb, QSpinBox) else 1
            price_w = self._lines_table.cellWidget(r, 3)
            price_p = parse_bdt(price_w.text()) if isinstance(price_w, QLineEdit) else 0
            lines.append(invoice_service.InvoiceLineInput(
                item_type="custom" if ref_id is None else "catalog",
                reference_id=ref_id,
                description=desc,
                quantity=qty,
                unit_price_paisa=price_p,
            ))
        return lines

    def _recalc_totals_display(self) -> None:
        sub = 0
        for r in range(self._lines_table.rowCount()):
            qty_w = self._lines_table.cellWidget(r, 2)
            price_w = self._lines_table.cellWidget(r, 3)
            total_lbl = self._lines_table.cellWidget(r, 4)
            qty = int(qty_w.value()) if isinstance(qty_w, QSpinBox) else 1
            price = parse_bdt(price_w.text()) if isinstance(price_w, QLineEdit) else 0
            line_total = max(0, qty * price)
            sub += line_total
            if isinstance(total_lbl, QLabel):
                total_lbl.setText(format_bdt(line_total))
        disc = parse_bdt(self._discount.text())
        tax = parse_bdt(self._tax.text())
        total = max(0, sub - disc + tax)
        paid = self._current_paid_paisa()
        self._sub_lbl.setText(f"Subtotal: {format_bdt(sub)}")
        self._disc_lbl.setText(f"Discount: {format_bdt(disc)}")
        self._tax_lbl.setText(f"Tax: {format_bdt(tax)}")
        self._tot_lbl.setText(f"TOTAL: {format_bdt(total)}")
        self._paid_lbl.setText(f"Paid: {format_bdt(paid)}")
        self._due_lbl.setText(f"Due: {format_bdt(max(0, total - paid))}")

    def _current_paid_paisa(self) -> int:
        # Recompute from visible payment table
        total = 0
        for r in range(self._pay_table.rowCount()):
            w = self._pay_table.cellWidget(r, 2)
            if isinstance(w, QLabel) and not getattr(w, "_reversed", False):
                total += parse_bdt(w.text())
        return total

    # ------------------------------------------------------ visit load
    def _on_load_from_visit(self) -> None:
        if self._visit_id is None:
            return
        self._load_from_visit()

    def _load_from_visit(self) -> None:
        assert self._visit_id is not None
        with UnitOfWork(self._session_factory) as uow:
            recs = treatment_service.list_treatments_for_visit(uow.session, self._principal, self._visit_id)
        self._lines_table.setRowCount(0)
        for t in recs:
            desc = t.name_at_service_time + (f" ({t.tooth_codes})" if t.tooth_codes else "")
            self._add_row(desc=desc, price=t.price_paisa)
        self._recalc_totals_display()

    # ------------------------------------------------------ payments UI
    def _reload_payments(self) -> None:
        self._pay_table.setRowCount(0)
        if self._invoice_id is None:
            return
        with UnitOfWork(self._session_factory) as uow:
            pays = payment_service.list_payments(uow.session, self._principal, invoice_id=self._invoice_id)
        for p in pays:
            r = self._pay_table.rowCount()
            self._pay_table.insertRow(r)
            self._pay_table.setItem(r, 0, QTableWidgetItem(format_datetime(p.paid_at)))
            self._pay_table.setItem(r, 1, QTableWidgetItem(p.method_name))
            amt_lbl = QLabel(format_bdt(p.amount_paisa), self._pay_table)
            amt_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if p.reversed_at is not None:
                amt_lbl.setStyleSheet("color:#98A2B3; text-decoration: line-through;")
                amt_lbl._reversed = True  # type: ignore[attr-defined]
            else:
                amt_lbl._reversed = False  # type: ignore[attr-defined]
            self._pay_table.setCellWidget(r, 2, amt_lbl)
            self._pay_table.setItem(r, 3, QTableWidgetItem(p.reference_no))
            self._pay_table.setItem(r, 4, QTableWidgetItem(p.notes + (f" (Reversed: {p.reversal_reason})" if p.reversed_at else "")))
            cell = QWidget(self._pay_table)
            h = QHBoxLayout(cell)
            h.setContentsMargins(Spacing.S1, Spacing.S1, Spacing.S1, Spacing.S1)
            h.setSpacing(Spacing.S1)
            if p.reversed_at is None and self._principal.has(Permission.PAYMENTS_REFUND):
                rv = QPushButton("Reverse", cell)
                rv.clicked.connect(lambda _=False, pid=p.id: self._on_reverse_payment(pid))
                h.addWidget(rv)
            self._pay_table.setCellWidget(r, 5, cell)
        self._recalc_totals_display()

    def _on_record_payment(self) -> None:
        if self._invoice_id is None:
            self._error.setText("Save or post the invoice first before recording payments.")
            return
        method_id = self._pay_method.currentData()
        amount = parse_bdt(self._pay_amount.text())
        if not isinstance(method_id, int) or amount <= 0:
            self._error.setText("Select a payment method and enter an amount greater than zero.")
            return
        try:
            with UnitOfWork(self._session_factory) as uow:
                payment_service.record_payment(uow.session, self._principal, payment_service.PaymentInput(
                    invoice_id=self._invoice_id, method_id=method_id,
                    amount_paisa=amount, reference_no=self._pay_ref.text().strip(),
                    notes=self._pay_notes.text().strip(),
                ))
                uow.commit()
        except DentivaError as e:
            self._error.setText(e.user_message)
            return
        self._pay_amount.setText("")
        self._pay_ref.setText("")
        self._pay_notes.setText("")
        self._error.setText("")
        self._refresh_invoice()
        self._reload_payments()

    def _on_reverse_payment(self, pay_id: int) -> None:
        from PySide6.QtWidgets import QInputDialog
        reason, ok = QInputDialog.getText(self, "Reverse payment", "Reason for reversal/refund:")
        if not ok or not reason.strip():
            return
        try:
            with UnitOfWork(self._session_factory) as uow:
                payment_service.reverse_payment(uow.session, self._principal, pay_id, reason=reason.strip())
                uow.commit()
        except DentivaError as e:
            self._error.setText(e.user_message)
            return
        self._refresh_invoice()
        self._reload_payments()

    # ------------------------------------------------------ save / post / void
    def _gather_data(self) -> invoice_service.InvoiceInput:
        dt_qt = self._date.dateTime().toPython()
        if isinstance(dt_qt, dt.datetime):
            if dt_qt.tzinfo is not None:
                from dentiva.core.dates import TZ
                date = dt_qt.astimezone(TZ).replace(tzinfo=None)
            else:
                date = dt_qt
        elif isinstance(dt_qt, dt.date):
            date = dt.datetime.combine(dt_qt, dt.time())
        else:
            date = local_now()
        return invoice_service.InvoiceInput(
            patient_id=self._patient.id,
            visit_id=self._visit_id,
            date=date,
            discount_paisa=parse_bdt(self._discount.text()),
            tax_paisa=parse_bdt(self._tax.text()),
            notes=self._notes.toPlainText().strip(),
            lines=self._collect_lines(),
        )

    def _on_save_draft(self) -> None:
        self._error.setText("")
        data = self._gather_data()
        try:
            with UnitOfWork(self._session_factory) as uow:
                if self._invoice_id is None:
                    inv = invoice_service.create_invoice(uow.session, self._principal, data)
                else:
                    inv = invoice_service.update_invoice(uow.session, self._principal, self._invoice_id, data)
                uow.commit()
                self._invoice_id = inv.id
        except ValidationError as e:
            self._error.setText(e.user_message)
            return
        except DentivaError as e:
            self._error.setText(e.user_message)
            return
        self._refresh_invoice()

    def _on_post(self) -> None:
        self._error.setText("")
        data = self._gather_data()
        try:
            with UnitOfWork(self._session_factory) as uow:
                if self._invoice_id is None:
                    inv = invoice_service.create_invoice(uow.session, self._principal, data)
                    self._invoice_id = inv.id
                else:
                    inv = invoice_service.update_invoice(uow.session, self._principal, self._invoice_id, data)
                inv = invoice_service.post_invoice(uow.session, self._principal, inv.id)
                uow.commit()
        except ValidationError as e:
            self._error.setText(e.user_message)
            return
        except DentivaError as e:
            self._error.setText(e.user_message)
            return
        self._refresh_invoice()

    def _on_void(self) -> None:
        if self._invoice_id is None:
            return
        from PySide6.QtWidgets import QInputDialog
        reason, ok = QInputDialog.getText(self, "Void invoice", "Reason for voiding:")
        if not ok or not reason.strip():
            return
        try:
            with UnitOfWork(self._session_factory) as uow:
                invoice_service.void_invoice(uow.session, self._principal, self._invoice_id, reason.strip())
                uow.commit()
        except DentivaError as e:
            self._error.setText(e.user_message)
            return
        self._refresh_invoice()

    def _refresh_invoice(self) -> None:
        if self._invoice_id is None:
            return
        with UnitOfWork(self._session_factory) as uow:
            self._invoice = invoice_service.get_invoice(uow.session, self._principal, self._invoice_id)
        self._load()

    def _on_print(self) -> None:
        if self._invoice_id is None:
            return
        try:
            with UnitOfWork(self._session_factory) as uow:
                inv = invoice_service.get_invoice(uow.session, self._principal, self._invoice_id)
                pays = payment_service.list_payments(uow.session, self._principal,
                                                     invoice_id=inv.id, include_reversed=False)
                from dentiva.printing.builders import build_invoice_doc
                doc = build_invoice_doc(uow.session, inv, pays, paper="a4")
            from dentiva.printing.manager import preview_document
            preview_document(self, doc, paper_code="a4")
        except DentivaError as e:
            QMessageBox.warning(self, "Print", e.user_message)

    def _on_pdf(self) -> None:
        if self._invoice_id is None:
            return
        try:
            with UnitOfWork(self._session_factory) as uow:
                inv = invoice_service.get_invoice(uow.session, self._principal, self._invoice_id)
                pays = payment_service.list_payments(uow.session, self._principal,
                                                     invoice_id=inv.id, include_reversed=False)
                from dentiva.printing.builders import build_invoice_doc
                doc = build_invoice_doc(uow.session, inv, pays, paper="a4")
            from dentiva.printing.manager import export_pdf
            export_pdf(self, doc, default_name=f"{inv.invoice_number}.pdf", paper_code="a4")
        except DentivaError as e:
            QMessageBox.warning(self, "PDF", e.user_message)
