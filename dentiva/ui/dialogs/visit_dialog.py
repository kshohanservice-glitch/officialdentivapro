"""New/edit visit dialog with dental chart, treatments and prescription tabs."""
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from dentiva.core.dates import format_datetime
from dentiva.core.errors import DentivaError, ValidationError
from dentiva.core.money import format_bdt
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.models import Patient
from dentiva.services import dentist_service, prescription_service, treatment_service, visit_service
from dentiva.ui.design_tokens import Spacing
from dentiva.ui.dialogs.prescription_dialog import PrescriptionDialog
from dentiva.ui.widgets.dental_chart import DentalChartWidget

if TYPE_CHECKING:
    from dentiva.core.permissions import Principal


class VisitDialog(QDialog):
    """Create or edit a visit with embedded dental chart, treatments and prescription."""

    def __init__(
        self,
        session_factory,
        principal: Principal,
        patient: Patient,
        *,
        visit=None,
        prefill_chart: dict[str, str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal
        self._patient = patient
        self._visit = visit
        self._visit_id: int | None = visit.id if visit is not None else None
        self.setMinimumSize(980, 720)
        self.setWindowTitle(f"{'Edit' if visit else 'New'} visit — {patient.name}")
        self.setModal(True)

        root = QVBoxLayout(self)

        form_wrap = QHBoxLayout()
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self._patient_label = QLabel(f"{patient.name} ({patient.patient_code})", self)
        self._patient_label.setStyleSheet("font-weight:600;")
        form.addRow("Patient", self._patient_label)

        self._date = QDateTimeEdit(self)
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._date.setDateTime(QDateTime.currentDateTime())
        form.addRow("Date & time", self._date)

        self._dentist = QComboBox(self)
        self._dentist.addItem("— Unassigned —", None)
        with UnitOfWork(session_factory) as uow:
            dentists = dentist_service.list_dentists(uow.session, principal, include_inactive=False)
        for d in dentists:
            self._dentist.addItem(d.name, d.id)
        form.addRow("Dentist", self._dentist)

        self._is_ped = QComboBox(self)
        self._is_ped.addItem("Adult (permanent)", False)
        self._is_ped.addItem("Pediatric (deciduous)", True)
        self._is_ped.currentIndexChanged.connect(self._on_layout_changed)
        form.addRow("Chart type", self._is_ped)

        self._reason = QLineEdit(self)
        self._reason.setPlaceholderText("e.g. Routine checkup, Toothache")
        form.addRow("Reason", self._reason)

        self._cc = QPlainTextEdit(self)
        self._cc.setFixedHeight(50)
        form.addRow("Chief complaint", self._cc)

        self._oe = QPlainTextEdit(self)
        self._oe.setFixedHeight(50)
        form.addRow("On examination", self._oe)

        self._advice = QPlainTextEdit(self)
        self._advice.setFixedHeight(50)
        form.addRow("Advice / Treatment plan", self._advice)

        self._notes = QPlainTextEdit(self)
        self._notes.setFixedHeight(40)
        form.addRow("Notes", self._notes)

        form_wrap.addLayout(form, 1)
        root.addLayout(form_wrap)

        # Tabs: Chart / Treatments / Prescription
        self._tabs = QTabWidget(self)

        # --- chart tab ---
        chart_tab = QWidget(self)
        cl = QVBoxLayout(chart_tab)
        cl.setContentsMargins(0, Spacing.S2, 0, 0)
        self._chart = DentalChartWidget(pediatric=False, editable=True, parent=chart_tab)
        if prefill_chart:
            self._chart.set_state(prefill_chart)
        cl.addWidget(self._chart, 1)
        self._tabs.addTab(chart_tab, "Dental chart")

        # --- treatments tab ---
        treat_tab = QWidget(self)
        tl = QVBoxLayout(treat_tab)
        tl.setContentsMargins(0, Spacing.S2, 0, 0)
        tbar = QHBoxLayout()
        self._add_treat = QPushButton("+ Add treatment", treat_tab)
        self._add_treat.setProperty("variant", "primary")
        self._add_treat.clicked.connect(self._on_add_treatment)
        tbar.addWidget(self._add_treat)
        tbar.addStretch(1)
        self._treat_total = QLabel("Total: ৳0.00", treat_tab)
        self._treat_total.setStyleSheet("font-weight:600;")
        tbar.addWidget(self._treat_total)
        tl.addLayout(tbar)

        self._treat_table = QTableWidget(0, 5, treat_tab)
        self._treat_table.setObjectName("DpDataTable")
        self._treat_table.setHorizontalHeaderLabels(["Treatment", "Teeth", "Price", "Notes", ""])
        self._treat_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._treat_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._treat_table.verticalHeader().setVisible(False)
        th = self._treat_table.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.Stretch)
        th.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        th.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        th.setSectionResizeMode(3, QHeaderView.Stretch)
        th.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        tl.addWidget(self._treat_table, 1)
        self._tabs.addTab(treat_tab, "Treatments")

        # --- prescription tab ---
        rx_tab = QWidget(self)
        rl = QVBoxLayout(rx_tab)
        rl.setContentsMargins(0, Spacing.S2, 0, 0)
        rx_bar = QHBoxLayout()
        self._rx_summary = QLabel("Save the visit first to draft a prescription.", rx_tab)
        rx_bar.addWidget(self._rx_summary, 1)
        self._rx_btn = QPushButton("Write prescription", rx_tab)
        self._rx_btn.setProperty("variant", "primary")
        self._rx_btn.clicked.connect(self._on_write_rx)
        self._rx_btn.setEnabled(False)
        rx_bar.addWidget(self._rx_btn)
        rl.addLayout(rx_bar)

        self._rx_list = QTableWidget(0, 3, rx_tab)
        self._rx_list.setObjectName("DpDataTable")
        self._rx_list.setHorizontalHeaderLabels(["Status", "Date", "Medicines"])
        self._rx_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._rx_list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._rx_list.verticalHeader().setVisible(False)
        rh = self._rx_list.horizontalHeader()
        rh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        rh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        rh.setSectionResizeMode(2, QHeaderView.Stretch)
        rl.addWidget(self._rx_list, 1)
        self._tabs.addTab(rx_tab, "Prescription")

        root.addWidget(self._tabs, 1)

        self._error = QLabel("", self)
        self._error.setObjectName("DpFieldError")
        self._error.setWordWrap(True)
        root.addWidget(self._error)

        btns = QHBoxLayout()
        btns.addStretch(1)
        if visit is None:
            self._save_open = QPushButton("Save & keep open", self)
            self._save_open.clicked.connect(lambda: self._save(close_after=False))
            self._save_close = QPushButton("Save & close visit", self)
            self._save_close.setProperty("variant", "primary")
            self._save_close.clicked.connect(lambda: self._save(close_after=True))
            cancel = QPushButton("Cancel", self)
            cancel.clicked.connect(self.reject)
            btns.addWidget(cancel)
            btns.addWidget(self._save_open)
            btns.addWidget(self._save_close)
        else:
            save = QPushButton("Save", self)
            save.setProperty("variant", "primary")
            save.clicked.connect(lambda: self._save(close_after=False))
            close_btn = QPushButton("Save & close visit", self)
            close_btn.clicked.connect(lambda: self._save(close_after=True))
            cancel = QPushButton("Cancel", self)
            cancel.clicked.connect(self.reject)
            btns.addWidget(cancel)
            btns.addWidget(save)
            btns.addWidget(close_btn)
        root.addLayout(btns)

        if visit is not None:
            self._load_visit(visit)
        if self._visit_id is not None:
            self._reload_treatments()
            self._reload_rx()

    # ----------------------------------------------------------- chart swap
    def _on_layout_changed(self) -> None:
        pediatric = bool(self._is_ped.currentData())
        state = self._chart.get_state()
        parent_layout = self._chart.parentWidget().layout() if self._chart.parentWidget() else None
        self._chart.setParent(None)
        self._chart.deleteLater()
        self._chart = DentalChartWidget(pediatric=pediatric, editable=True, parent=self._tabs.widget(0))
        self._chart.set_state(state if not pediatric else {})
        if parent_layout is not None:
            parent_layout.insertWidget(0, self._chart, 1)

    def _load_visit(self, v) -> None:
        self._reason.setText(v.reason)
        self._cc.setPlainText(v.chief_complaint)
        self._oe.setPlainText(v.on_examination)
        self._advice.setPlainText(v.advice)
        self._notes.setPlainText(v.notes)
        if v.visit_date is not None:
            qdt = QDateTime.fromString(v.visit_date.strftime("%Y-%m-%d %H:%M"), "yyyy-MM-dd HH:mm")
            self._date.setDateTime(qdt)
        idx = self._dentist.findData(None)
        self._dentist.setCurrentIndex(max(0, idx))
        state = {f.tooth_code: f.finding for f in v.findings}
        self._chart.set_state(state)

    # ----------------------------------------------------- treatments / rx
    def _reload_treatments(self) -> None:
        if self._visit_id is None:
            self._treat_table.setRowCount(0)
            self._treat_total.setText("Total: ৳0.00")
            return
        with UnitOfWork(self._session_factory) as uow:
            recs = treatment_service.list_treatments_for_visit(uow.session, self._principal, self._visit_id)
            total = treatment_service.visit_total_paisa(uow.session, self._visit_id)
        self._treat_table.setRowCount(0)
        for t in recs:
            r = self._treat_table.rowCount()
            self._treat_table.insertRow(r)
            self._treat_table.setItem(r, 0, QTableWidgetItem(t.name_at_service_time))
            teeth_text = t.tooth_codes if t.tooth_codes else "—"
            self._treat_table.setItem(r, 1, QTableWidgetItem(teeth_text))
            self._treat_table.setItem(r, 2, QTableWidgetItem(format_bdt(t.price_paisa)))
            self._treat_table.setItem(r, 3, QTableWidgetItem(t.notes or ""))
            cell = QWidget(self._treat_table)
            h = QHBoxLayout(cell)
            h.setContentsMargins(Spacing.S1, Spacing.S1, Spacing.S1, Spacing.S1)
            h.setSpacing(Spacing.S1)
            rm = QPushButton("Remove", cell)
            rm.clicked.connect(lambda _=False, tid=t.id: self._remove_treatment(tid))
            h.addWidget(rm)
            self._treat_table.setCellWidget(r, 4, cell)
        self._treat_total.setText(f"Total: {format_bdt(total)}")

    def _on_add_treatment(self) -> None:
        if self._visit_id is None:
            if not self._save_visit_draft():
                return
        dlg = QDialog(self)
        dlg.setWindowTitle("Add treatment")
        dlg.setModal(True)
        f = QFormLayout(dlg)
        catalog_combo = QComboBox(dlg)
        catalog_combo.addItem("Custom (not in catalog)", None)
        with UnitOfWork(self._session_factory) as uow:
            items = treatment_service.list_catalog(uow.session, self._principal, active_only=True)
        for t in items:
            catalog_combo.addItem(f"{t.name} — {format_bdt(t.default_price_paisa)}", t.id)
        teeth = QLineEdit(dlg)
        teeth.setPlaceholderText("e.g. 36, 46 (FDI codes, optional)")
        price = QLineEdit(dlg)
        price.setPlaceholderText("Price in ৳ (leave blank for catalog default)")
        notes = QLineEdit(dlg)
        notes.setPlaceholderText("Optional notes")
        f.addRow("Treatment catalog", catalog_combo)
        f.addRow("Tooth codes", teeth)
        f.addRow("Price", price)
        f.addRow("Notes", notes)
        err = QLabel("", dlg)
        err.setObjectName("DpFieldError")
        err.setWordWrap(True)
        f.addRow(err)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, dlg)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if not dlg.exec():
            return
        price_paisa = 0
        if price.text().strip():
            try:
                price_paisa = int(float(price.text().strip()) * 100)
            except ValueError:
                err.setText("Price must be a number.")
                return
        try:
            assert self._visit_id is not None
            with UnitOfWork(self._session_factory) as uow:
                treatment_service.add_treatment_to_visit(
                    uow.session, self._principal, self._visit_id,
                    treatment_service.TreatmentRecordInput(
                        catalog_id=catalog_combo.currentData(),
                        tooth_codes=teeth.text().strip(),
                        price_paisa=price_paisa,
                        notes=notes.text().strip(),
                    ),
                )
                uow.commit()
        except ValidationError as e:
            err.setText(e.user_message)
            return
        except DentivaError as e:
            err.setText(e.user_message)
            return
        self._reload_treatments()

    def _remove_treatment(self, tid: int) -> None:
        try:
            with UnitOfWork(self._session_factory) as uow:
                treatment_service.delete_treatment_record(uow.session, self._principal, tid)
                uow.commit()
        except DentivaError as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Cannot remove", e.user_message)
            return
        self._reload_treatments()

    def _reload_rx(self) -> None:
        self._rx_list.setRowCount(0)
        if self._visit_id is None:
            self._rx_summary.setText("Save the visit first to draft a prescription.")
            self._rx_btn.setEnabled(False)
            return
        from dentiva.core.permissions import Permission
        self._rx_btn.setEnabled(self._principal.has(Permission.PRESCRIPTIONS_CREATE))
        with UnitOfWork(self._session_factory) as uow:
            rxs = prescription_service.list_prescriptions(
                uow.session, self._principal, visit_id=self._visit_id
            )
        if not rxs:
            self._rx_summary.setText("No prescription drafted yet for this visit.")
            self._rx_btn.setText("Write prescription")
            return
        latest = rxs[0]
        n_meds = len(latest.medicines)
        status_word = "Finalized" if latest.finalized else "Draft"
        self._rx_summary.setText(f"Latest: {status_word} — {n_meds} medicine(s).")
        self._rx_btn.setText("Open / edit prescription")
        for rx in rxs:
            r = self._rx_list.rowCount()
            self._rx_list.insertRow(r)
            s = QTableWidgetItem("Finalized" if rx.finalized else "Draft")
            s.setForeground(QColor("#027A48" if rx.finalized else "#B54708"))
            self._rx_list.setItem(r, 0, s)
            self._rx_list.setItem(r, 1, QTableWidgetItem(format_datetime(rx.date)))
            med_names = [m.name for m in rx.medicines[:3]]
            meds = ", ".join(med_names)
            if len(rx.medicines) > 3:
                meds += f" … (+{len(rx.medicines) - 3})"
            self._rx_list.setItem(r, 2, QTableWidgetItem(meds))
            self._rx_list.item(r, 0).setData(Qt.UserRole, rx.id)

    def _on_write_rx(self) -> None:
        if self._visit_id is None:
            return
        with UnitOfWork(self._session_factory) as uow:
            rxs = prescription_service.list_prescriptions(
                uow.session, self._principal, visit_id=self._visit_id
            )
            if rxs:
                rx = prescription_service.get_prescription(uow.session, self._principal, rxs[0].id)
            else:
                rx = None
        dlg = PrescriptionDialog(
            self._session_factory, self._principal,
            prescription=rx,
            patient_id=self._patient.id,
            visit_id=self._visit_id,
            dentist_id=self._dentist.currentData(),
            parent=self,
        )
        if dlg.exec():
            self._reload_rx()

    def _save_visit_draft(self) -> bool:
        self._error.setText("")
        dt_qt = self._date.dateTime().toPython()
        visit_date: dt.datetime | None
        if isinstance(dt_qt, dt.datetime):
            if dt_qt.tzinfo is not None:
                from dentiva.core.dates import TZ
                dt_qt = dt_qt.astimezone(TZ).replace(tzinfo=None)
            visit_date = dt_qt
        elif isinstance(dt_qt, dt.date):
            visit_date = dt.datetime.combine(dt_qt, dt.time())
        else:
            visit_date = None
        data = visit_service.VisitInput(
            dentist_id=self._dentist.currentData(),
            visit_date=visit_date,
            reason=self._reason.text(),
            chief_complaint=self._cc.toPlainText(),
            on_examination=self._oe.toPlainText(),
            advice=self._advice.toPlainText(),
            notes=self._notes.toPlainText(),
            is_pediatric=bool(self._is_ped.currentData()),
            findings=self._chart.get_state(),
        )
        try:
            with UnitOfWork(self._session_factory) as uow:
                if self._visit_id is None:
                    v = visit_service.create_visit(uow.session, self._principal, self._patient.id, data)
                    self._visit_id = v.id
                else:
                    visit_service.update_visit(uow.session, self._principal, self._visit_id, data)
                uow.commit()
        except ValidationError as e:
            self._error.setText(e.user_message)
            return False
        except DentivaError as e:
            self._error.setText(e.user_message)
            return False
        self._reload_treatments()
        self._reload_rx()
        return True

    # ---------------------------------------------------------------- save
    def _save(self, *, close_after: bool) -> None:
        self._error.setText("")
        if not self._save_visit_draft():
            return
        assert self._visit_id is not None
        if close_after:
            try:
                with UnitOfWork(self._session_factory) as uow:
                    visit_service.close_visit(uow.session, self._principal, self._visit_id)
                    uow.commit()
            except ValidationError as e:
                self._error.setText(e.user_message)
                return
            except DentivaError as e:
                self._error.setText(e.user_message)
                return
        self.accept()
