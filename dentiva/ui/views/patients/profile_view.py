"""Patient profile view — tabbed summary, visits/chart, prescriptions, invoices, attachments.

Phase 6 ships the Summary tab + Visits tab (with embedded dental chart for
new and historical visits) and placeholders for the remaining tabs that
will be filled by later phases as their modules are built.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from dentiva.core.dates import format_date, format_datetime
from dentiva.core.money import format_bdt
from dentiva.core.permissions import Permission, Principal
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import invoice_service, patient_service, visit_service
from dentiva.ui.design_tokens import Spacing
from dentiva.ui.dialogs.invoice_dialog import InvoiceDialog
from dentiva.ui.dialogs.patient_dialog import PatientFormDialog, confirm_delete_patient
from dentiva.ui.dialogs.prescription_dialog import PrescriptionDialog
from dentiva.ui.dialogs.visit_dialog import VisitDialog
from dentiva.ui.widgets.cards import Card
from dentiva.ui.widgets.dental_chart import FINDING_CODE_TO_LABEL, DentalChartWidget
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:

    from dentiva.models import Patient
    from sqlalchemy.orm import sessionmaker


class PatientProfileView(QWidget):
    """Displays a single patient's data. Constructed with a patient id; call
    :meth:`load_patient` to (re)load data. Exposes a ``back_requested``
    signal for returning to the patients list."""

    back_requested = Signal()

    def __init__(self, session_factory: sessionmaker, principal: Principal, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal
        self._patient: Patient | None = None
        self._current_chart_state: dict[str, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.S4)

        # Header row (back button + name + actions)
        hdr = QHBoxLayout()
        back = QPushButton("← Patients", self)
        back.clicked.connect(self.back_requested.emit)
        hdr.addWidget(back)
        self._name_lbl = QLabel("", self)
        self._name_lbl.setObjectName("DpPageTitle")
        hdr.addWidget(self._name_lbl, 1)
        self._edit_btn = QPushButton("Edit", self)
        self._edit_btn.clicked.connect(self._on_edit)
        self._edit_btn.setVisible(self._principal.has(Permission.PATIENTS_EDIT))
        hdr.addWidget(self._edit_btn)
        self._delete_btn = QPushButton("Delete", self)
        self._delete_btn.setProperty("variant", "destructive")
        self._delete_btn.clicked.connect(self._on_delete)
        self._delete_btn.setVisible(self._principal.has(Permission.PATIENTS_DELETE))
        hdr.addWidget(self._delete_btn)
        root.addLayout(hdr)

        self._meta_lbl = QLabel("", self)
        self._meta_lbl.setObjectName("DpPageSubtitle")
        self._meta_lbl.setWordWrap(True)
        root.addWidget(self._meta_lbl)

        # Tabs
        self._tabs = QTabWidget(self)

        # Summary
        self._summary = QWidget(self)
        self._build_summary_tab(self._summary)
        self._tabs.addTab(self._summary, "Summary")

        # Visits + chart
        self._visits = QWidget(self)
        self._build_visits_tab(self._visits)
        self._tabs.addTab(self._visits, "Visits & Chart")

        # Placeholder / populated tabs
        self._rx_tab = QWidget(self)
        self._build_rx_tab(self._rx_tab)
        self._tabs.addTab(self._rx_tab, "Prescriptions")

        self._inv_tab = QWidget(self)
        self._build_invoices_tab(self._inv_tab)
        self._tabs.addTab(self._inv_tab, "Invoices")

        from dentiva.ui.widgets.attachment_panel import AttachmentPanel
        self._attachments_tab = AttachmentPanel(
            self._session_factory, self._principal,
            attachable_type="patient",
            attachable_id_getter=self._current_patient_id,
            parent=self._tabs,
        )
        self._tabs.addTab(self._attachments_tab, "Attachments")

        root.addWidget(self._tabs, 1)

    # ----------------------------------------------------------------- API
    def _current_patient_id(self) -> int | None:
        return self._patient.id if self._patient is not None else None

    def load_patient(self, patient_id: int) -> None:
        with UnitOfWork(self._session_factory) as uow:
            self._patient = patient_service.get_patient(uow.session, patient_id)
            uow.commit()
        self._populate()
        self._attachments_tab.refresh()

    # ------------------------------------------------------------- populate
    def _populate(self) -> None:
        p = self._patient
        if p is None:
            return
        self._name_lbl.setText(f"{p.name}")
        meta_parts = [f"Code: <b>{p.patient_code}</b>"]
        if p.phone:
            meta_parts.append(f"📞 {p.phone}")
        if p.gender:
            meta_parts.append(p.gender)
        if p.age_cache is not None:
            meta_parts.append(f"Age {p.age_cache}")
        if p.blood_group:
            meta_parts.append(f"Blood {p.blood_group}")
        if p.last_visit_at:
            meta_parts.append(f"Last visit {format_datetime(p.last_visit_at)}")
        meta_parts.append(f"{p.visit_count or 0} visit(s)")
        self._meta_lbl.setText(" · ".join(meta_parts))

        # Summary tab
        self._summary_name.setText(p.name)
        self._summary_code.setText(p.patient_code)
        self._summary_phone.setText(p.phone or "—")
        self._summary_emergency.setText(p.emergency_phone or "—")
        self._summary_email.setText(p.email or "—")
        self._summary_gender.setText(p.gender or "—")
        self._summary_age.setText(str(p.age_cache) if p.age_cache is not None else "—")
        self._summary_dob.setText(format_date(p.dob) if p.dob else "—")
        self._summary_blood.setText(p.blood_group or "—")
        self._summary_address.setPlainText(p.address or "—")
        self._summary_cc.setPlainText(p.chief_complaint or "—")
        self._summary_history.setPlainText(p.medical_history or "—")
        self._summary_allergies.setPlainText(p.allergies or "—")
        self._summary_notes.setPlainText(p.notes or "—")

        # Visits list
        self._reload_visits()
        self._reload_rx()
        self._reload_invoices()

    def _reload_visits(self) -> None:
        if self._patient is None:
            return
        with UnitOfWork(self._session_factory) as uow:
            visits = visit_service.list_visits(uow.session, self._principal, self._patient.id)
            # Current chart state (latest finding per tooth across all visits)
            self._current_chart_state = visit_service.latest_chart_state(uow.session, self._patient.id)
            uow.commit()
        self._visit_list.clear()
        for v in visits:
            date_str = format_datetime(v.visit_date)
            title = f"{date_str}  ·  {v.dentist_name}  ·  {v.status.title()}"
            if v.reason:
                title += f"  —  {v.reason}"
            it = QListWidgetItem(title, self._visit_list)
            it.setData(Qt.UserRole, v.id)
        self._chart.set_state(self._current_chart_state)
        self._chart.set_editable(False)
        self._chart.updateGeometry()

    # ---------------------------------------------------------- tabs build
    def _build_summary_tab(self, w: QWidget) -> None:
        v = QVBoxLayout(w)
        v.setSpacing(Spacing.S4)
        grid = QGridLayout()
        grid.setSpacing(Spacing.S3)

        def add_kpi(row: int, label: str, widget_attr: str) -> QLabel:
            lbl = QLabel(label, self)
            lbl.setStyleSheet("color:#667085;font-size:11px;")
            val = QLabel("—", self)
            val.setStyleSheet("font-weight:600;font-size:13px;")
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(lbl, row, 0)
            grid.addWidget(val, row, 1)
            setattr(self, widget_attr, val)
            return val

        self._summary_name = QLabel("", self)
        self._summary_name.setStyleSheet("font-size:16px;font-weight:700;")
        grid.addWidget(self._summary_name, 0, 0, 1, 4)
        add_kpi(1, "Code", "_summary_code")
        add_kpi(1, "Phone", "_summary_phone")
        add_kpi(2, "Emergency", "_summary_emergency")
        add_kpi(2, "Email", "_summary_email")
        add_kpi(3, "Gender", "_summary_gender")
        add_kpi(3, "Age", "_summary_age")
        add_kpi(4, "DOB", "_summary_dob")
        add_kpi(4, "Blood group", "_summary_blood")
        v.addLayout(grid)

        # Clinical info card
        clin = Card(self)
        clin.set_title("Clinical information")
        clin_grid = QGridLayout()
        clin_grid.setSpacing(Spacing.S3)
        self._summary_address = self._multiline("—")
        self._summary_cc = self._multiline("—")
        self._summary_history = self._multiline("—")
        self._summary_allergies = self._multiline("—")
        self._summary_notes = self._multiline("—")
        clin_grid.addWidget(QLabel("Address", self), 0, 0)
        clin_grid.addWidget(self._summary_address, 0, 1)
        clin_grid.addWidget(QLabel("Chief complaint", self), 1, 0)
        clin_grid.addWidget(self._summary_cc, 1, 1)
        clin_grid.addWidget(QLabel("Medical history", self), 2, 0)
        clin_grid.addWidget(self._summary_history, 2, 1)
        clin_grid.addWidget(QLabel("Allergies", self), 3, 0)
        clin_grid.addWidget(self._summary_allergies, 3, 1)
        clin_grid.addWidget(QLabel("Notes", self), 4, 0)
        clin_grid.addWidget(self._summary_notes, 4, 1)
        clin_grid.setColumnStretch(1, 1)
        clin.set_body_layout(clin_grid)
        v.addWidget(clin)
        v.addStretch(1)

    def _multiline(self, text: str) -> QLabel:
        w = QLabel(text, self)
        w.setWordWrap(True)
        w.setTextInteractionFlags(Qt.TextSelectableByMouse)
        w.setStyleSheet("color:#344054;")
        return w

    def _build_visits_tab(self, w: QWidget) -> None:
        h = QHBoxLayout(w)
        h.setSpacing(Spacing.S4)

        left = QVBoxLayout()
        left.setSpacing(Spacing.S3)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Visits", self))
        bar.addStretch(1)
        self._new_visit_btn = QPushButton("+ New visit", self)
        self._new_visit_btn.setProperty("variant", "primary")
        self._new_visit_btn.clicked.connect(self._on_new_visit)
        self._new_visit_btn.setVisible(self._principal.has(Permission.VISITS_CREATE))
        bar.addWidget(self._new_visit_btn)
        left.addLayout(bar)
        self._visit_list = QListWidget(self)
        self._visit_list.itemSelectionChanged.connect(self._on_visit_selected)
        left.addWidget(self._visit_list, 1)

        right = QVBoxLayout()
        right.setSpacing(Spacing.S3)
        right.addWidget(QLabel("Current dental chart", self))
        self._chart = DentalChartWidget(pediatric=False, editable=False, parent=self)
        right.addWidget(self._chart, 1)
        self._visit_detail = QLabel("Select a visit on the left to view findings, or click '+ New visit' to start one.", self)
        self._visit_detail.setWordWrap(True)
        self._visit_detail.setStyleSheet("color:#475467;")
        right.addWidget(self._visit_detail)

        h.addLayout(left, 1)
        h.addLayout(right, 2)

    # --------------------------------------------------------------- events
    def _on_edit(self) -> None:
        if self._patient is None:
            return
        dlg = PatientFormDialog(self._session_factory, self._principal, patient=self._patient, parent=self)
        if dlg.exec():
            self.load_patient(self._patient.id)

    def _on_delete(self) -> None:
        if self._patient is None:
            return
        if confirm_delete_patient(self, self._session_factory, self._principal, self._patient):
            self.back_requested.emit()

    def _on_new_visit(self) -> None:
        if self._patient is None:
            return
        dlg = VisitDialog(
            self._session_factory, self._principal, self._patient,
            prefill_chart=self._current_chart_state,
            parent=self,
        )
        if dlg.exec():
            self._reload_visits()
            self.load_patient(self._patient.id)

    def _on_visit_selected(self) -> None:
        item = self._visit_list.currentItem()
        if item is None or self._patient is None:
            return
        vid = item.data(Qt.UserRole)
        with UnitOfWork(self._session_factory) as uow:
            v = visit_service.get_visit(uow.session, self._principal, vid)
            uow.commit()
        # Build a description + per-tooth state.
        state = {f.tooth_code: f.finding for f in v.findings}
        # Detect pediatric quadrants (5-8) among the findings.
        ped = bool(state) and any(code[0] in "5678" for code in state)
        # Recreate chart widget if layout differs.
        self._chart.setParent(None)
        self._chart.deleteLater()
        self._chart = DentalChartWidget(pediatric=ped, editable=False, parent=self)
        self._chart.set_state(state)
        parent_layout = self._visits.layout().itemAt(1).layout()
        parent_layout.insertWidget(1, self._chart, 1)
        # Detail text
        tooth_lines = []
        for f in v.findings:
            tooth_lines.append(f"  • {f.tooth_code}: {FINDING_CODE_TO_LABEL.get(f.finding, f.finding)}")
        detail = (
            f"<b>{format_datetime(v.visit_date)}</b> — {v.dentist_name} "
            f"(<i>{v.status.title()}</i>)<br>"
            f"<b>Reason:</b> {v.reason or '—'}<br>"
            f"<b>Chief complaint:</b> {v.chief_complaint or '—'}<br>"
            f"<b>On exam:</b> {v.on_examination or '—'}<br>"
            f"<b>Advice:</b> {v.advice or '—'}<br>"
            f"<b>Findings:</b><br>{'<br>'.join(tooth_lines) if tooth_lines else 'No chart findings recorded.'}"
        )
        self._visit_detail.setText(detail)
        self._visit_detail.setTextFormat(Qt.RichText)

    # ------------------------------------------------------ Rx tab
    def _build_rx_tab(self, w: QWidget) -> None:
        v=QVBoxLayout(w)
        v.setSpacing(Spacing.S3)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Prescription history", w))
        bar.addStretch(1)
        self._new_rx_btn = QPushButton("+ New prescription", w)
        self._new_rx_btn.setProperty("variant", "primary")
        self._new_rx_btn.clicked.connect(self._on_new_rx)
        bar.addWidget(self._new_rx_btn)
        v.addLayout(bar)
        self._rx_table=QTableWidget(0,4,w)
        self._rx_table.setObjectName("DpDataTable")
        self._rx_table.setHorizontalHeaderLabels(["Date", "Medicines", "Status", ""])
        self._rx_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._rx_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._rx_table.doubleClicked.connect(lambda _i: self._on_open_rx())
        self._rx_table.verticalHeader().setVisible(False)
        hh = self._rx_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        v.addWidget(self._rx_table, 1)

    def _reload_rx(self) -> None:
        if self._patient is None:
            return

        self._rx_table.setRowCount(0)
        with UnitOfWork(self._session_factory) as uow:
            rxs = __import__("dentiva.services.prescription_service", fromlist=["prescription_service"]).prescription_service.list_prescriptions(
                uow.session, self._principal, patient_id=self._patient.id, limit=100)
            can_create = self._principal.has(Permission.PRESCRIPTIONS_CREATE)
            uow.commit()
        self._new_rx_btn.setEnabled(can_create)
        for rx in rxs:
            r=self._rx_table.rowCount()
            self._rx_table.insertRow(r)
            self._rx_table.setItem(r, 0, QTableWidgetItem(format_datetime(rx.date)))
            med_names = ", ".join(m.name for m in rx.medicines[:3])
            if len(rx.medicines) > 3:
                med_names += f" … (+{len(rx.medicines)-3})"

            self._rx_table.setItem(r, 1, QTableWidgetItem(med_names))
            s = QTableWidgetItem("Finalized" if rx.finalized else "Draft")
            s.setForeground(QColor("#027A48" if rx.finalized else "#B54708"))
            self._rx_table.setItem(r, 2, s)
            open_btn = QPushButton("Open", self._rx_table)
            open_btn.clicked.connect(lambda _=False, rid=rx.id: self._open_rx_by_id(rid))
            cell = QWidget(self._rx_table)
            ch=QHBoxLayout(cell)
            ch.setContentsMargins(Spacing.S1,Spacing.S1,Spacing.S1,Spacing.S1)
            ch.addWidget(open_btn)
            self._rx_table.setCellWidget(r, 3, cell)
            self._rx_table.item(r, 0).setData(Qt.UserRole, rx.id)

    def _on_new_rx(self) -> None:
        if self._patient is None:
            return

        dlg = PrescriptionDialog(self._session_factory, self._principal,
                                 patient_id=self._patient.id, parent=self)
        if dlg.exec():
            self._reload_rx()


    def _on_open_rx(self) -> None:
        r = self._rx_table.currentRow()
        if r < 0:
            return

        it = self._rx_table.item(r, 0)
        if it is None:
            return

        rid = it.data(Qt.UserRole)
        self._open_rx_by_id(int(rid))

    def _open_rx_by_id(self, rid: int) -> None:
        with UnitOfWork(self._session_factory) as uow:
            rx = __import__("dentiva.services.prescription_service", fromlist=["prescription_service"]).prescription_service.get_prescription(
                uow.session, self._principal, rid)
        dlg = PrescriptionDialog(self._session_factory, self._principal, prescription=rx, parent=self)
        if dlg.exec():
            self._reload_rx()


    # ------------------------------------------------------ Invoices tab
    def _build_invoices_tab(self, w: QWidget) -> None:
        v=QVBoxLayout(w)
        v.setSpacing(Spacing.S3)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Invoices", w))
        bar.addStretch(1)
        self._new_inv_btn = QPushButton("+ New invoice", w)
        self._new_inv_btn.setProperty("variant", "primary")
        self._new_inv_btn.clicked.connect(self._on_new_invoice)
        bar.addWidget(self._new_inv_btn)
        v.addLayout(bar)
        self._inv_table=QTableWidget(0,5,w)
        self._inv_table.setObjectName("DpDataTable")
        self._inv_table.setHorizontalHeaderLabels(["#", "Date", "Total", "Paid", "Due / Status"])
        self._inv_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._inv_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._inv_table.doubleClicked.connect(lambda _i: self._on_open_invoice())
        self._inv_table.verticalHeader().setVisible(False)
        hh = self._inv_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        v.addWidget(self._inv_table, 1)

    def _reload_invoices(self) -> None:
        if self._patient is None:
            return

        self._inv_table.setRowCount(0)
        with UnitOfWork(self._session_factory) as uow:
            invs = invoice_service.list_invoices(uow.session, self._principal, patient_id=self._patient.id, limit=100)
            can_create = self._principal.has(Permission.INVOICES_CREATE)
        self._new_inv_btn.setEnabled(can_create)
        status_colors = {"draft":"#B54708","unpaid":"#B42318","partial":"#B54708","paid":"#027A48","void":"#667085"}
        for inv in invs:
            r=self._inv_table.rowCount()
            self._inv_table.insertRow(r)
            self._inv_table.setItem(r, 0, QTableWidgetItem(inv.invoice_number))
            self._inv_table.setItem(r, 1, QTableWidgetItem(format_datetime(inv.date)))
            self._inv_table.setItem(r, 2, QTableWidgetItem(format_bdt(inv.total_paisa)))
            self._inv_table.setItem(r, 3, QTableWidgetItem(format_bdt(inv.paid_paisa)))
            due_text = f"{format_bdt(inv.due_paisa)}  ·  {inv.status.title()}"
            s = QTableWidgetItem(due_text)
            s.setForeground(QColor(status_colors.get(inv.status, "#475467")))
            self._inv_table.setItem(r, 4, s)
            self._inv_table.item(r, 0).setData(Qt.UserRole, inv.id)

    def _on_new_invoice(self) -> None:
        if self._patient is None:
            return

        dlg = InvoiceDialog(self._session_factory, self._principal, self._patient, parent=self)
        if dlg.exec():
            self._reload_invoices()

    def _on_open_invoice(self) -> None:
        r = self._inv_table.currentRow()
        if r < 0:
            return

        it = self._inv_table.item(r, 0)
        if it is None:
            return

        iid = it.data(Qt.UserRole)
        if not isinstance(iid, int):
            return

        if self._patient is None:
            return
        with UnitOfWork(self._session_factory) as uow:
            inv = invoice_service.get_invoice(uow.session, self._principal, iid)
        dlg = InvoiceDialog(self._session_factory, self._principal, self._patient, invoice=inv, parent=self)
        if dlg.exec():
            self._reload_invoices()
