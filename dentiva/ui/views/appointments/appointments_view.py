"""Appointments & Queue view: day view of appointments plus a live queue board.

Combines both concerns because in a clinic the appointments list and the
waiting queue operate off the same day/date and clinicians/receptionists
toggle between them constantly. Tabs separate (a) day view, (b) week view
(stub for Phase 7 — list is sufficient for v1), and (c) queue board.
"""
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from dentiva.core.dates import combine, format_datetime
from dentiva.core.errors import DentivaError, ValidationError
from dentiva.core.permissions import Permission, Principal
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import appointment_service, dentist_service, patient_service
from dentiva.ui.design_tokens import Spacing
from dentiva.ui.dialogs.appointment_dialog import AppointmentDialog
from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    pass


STATUS_COLOR = {
    "scheduled": "#475467",
    "confirmed": "#027A48",
    "checked_in": "#B54708",
    "in_progress": "#6941C6",
    "completed": "#98A2B3",
    "cancelled": "#B42318",
    "no_show": "#D92D20",
}


class AppointmentsView(QWidget):
    def __init__(self, session_factory, principal: Principal, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.S4)

        title = QLabel("Appointments & Queue", self)
        title.setObjectName("DpPageTitle")
        subtitle = QLabel("Schedule appointments, check patients in, and monitor the waiting queue.", self)
        subtitle.setObjectName("DpPageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        self._tabs = QTabWidget(self)
        self._day = QWidget(self)
        self._build_day_tab(self._day)
        self._queue_widget = QWidget(self)
        self._build_queue_tab(self._queue_widget)
        self._tabs.addTab(self._day, "Day view")
        self._tabs.addTab(self._queue_widget, "Queue")
        root.addWidget(self._tabs, 1)

        # Auto-refresh every 30 seconds for the queue board
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self._refresh_active_tab)
        self._timer.start()
        self._tabs.currentChanged.connect(lambda _i: self._refresh_active_tab())

        self.refresh()

    # ------------------------------------------------------------------ API
    def refresh(self) -> None:
        self._reload_day()
        self._reload_queue()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        QTimer.singleShot(0, self._refresh_active_tab)

    # --------------------------------------------------------------- helpers
    def _refresh_active_tab(self) -> None:
        idx = self._tabs.currentIndex()
        if idx == 0:
            self._reload_day()
        else:
            self._reload_queue()

    # ------------------------------------------------------------- day tab
    def _build_day_tab(self, w: QWidget) -> None:
        v = QVBoxLayout(w)
        v.setSpacing(Spacing.S3)
        bar = QHBoxLayout()
        bar.setSpacing(Spacing.S2)
        self._date_edit = QDateEdit(QDate.currentDate(), w)
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDisplayFormat("yyyy-MM-dd")
        self._date_edit.dateChanged.connect(lambda _q: self._reload_day())
        bar.addWidget(self._date_edit)

        self._dentist_filter = QComboBox(w)
        self._dentist_filter.addItem("All dentists", None)
        with UnitOfWork(self._session_factory) as uow:
            for d in dentist_service.list_dentists(uow.session, self._principal, include_inactive=False):
                self._dentist_filter.addItem(d.name, d.id)
        self._dentist_filter.currentIndexChanged.connect(lambda _i: self._reload_day())
        bar.addWidget(self._dentist_filter)
        bar.addStretch(1)

        self._new_btn = QPushButton("+ New appointment", w)
        self._new_btn.setProperty("variant", "primary")
        self._new_btn.clicked.connect(self._on_new)
        self._new_btn.setVisible(self._principal.has(Permission.APPOINTMENTS_CREATE))
        bar.addWidget(self._new_btn)
        v.addLayout(bar)

        self._day_table = QTableWidget(0, 7, w)
        self._day_table.setObjectName("DpDataTable")
        self._day_table.setHorizontalHeaderLabels(["Time", "Patient", "Phone", "Dentist", "Reason", "Status", "Actions"])
        self._day_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._day_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._day_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._day_table.verticalHeader().setVisible(False)
        hh = self._day_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        v.addWidget(self._day_table, 1)

    def _reload_day(self) -> None:
        qd = self._date_edit.date()
        d = dt.date(qd.year(), qd.month(), qd.day())
        day_start = combine(d, dt.time(0, 0))
        day_end = combine(d, dt.time(23, 59, 59))
        dentist_id = self._dentist_filter.currentData()
        with UnitOfWork(self._session_factory) as uow:
            appts = appointment_service.list_appointments(
                uow.session, self._principal,
                start=day_start, end=day_end,
                dentist_id=dentist_id,
                statuses=None,
            )
            uow.commit()
        self._day_table.setRowCount(0)
        for a in appts:
            r = self._day_table.rowCount()
            self._day_table.insertRow(r)
            self._day_table.setItem(r, 0, QTableWidgetItem(format_datetime(a.scheduled_at)))
            self._day_table.setItem(r, 1, QTableWidgetItem(a.patient_name))
            self._day_table.setItem(r, 2, QTableWidgetItem(a.patient_phone))
            self._day_table.setItem(r, 3, QTableWidgetItem(a.dentist_name))
            self._day_table.setItem(r, 4, QTableWidgetItem(a.reason))
            status_item = QTableWidgetItem(a.status.replace("_", " ").title())
            color = STATUS_COLOR.get(a.status)
            if color:
                status_item.setForeground(QColor(color))
            self._day_table.setItem(r, 5, status_item)
            # Action buttons
            cell = QWidget(self._day_table)
            h = QHBoxLayout(cell)
            h.setContentsMargins(Spacing.S1, Spacing.S1, Spacing.S1, Spacing.S1)
            h.setSpacing(Spacing.S1)
            edit_btn = QPushButton("Edit", cell)
            edit_btn.setEnabled(self._principal.has(Permission.APPOINTMENTS_EDIT))
            edit_btn.clicked.connect(lambda _=False, aid=a.id: self._on_edit(aid))
            h.addWidget(edit_btn)
            if a.status in {"scheduled", "confirmed"}:
                ci = QPushButton("Check in", cell)
                ci.setEnabled(self._principal.has(Permission.QUEUE_MANAGE))
                ci.setProperty("variant", "primary")
                ci.clicked.connect(lambda _=False, aid=a.id: self._on_check_in(aid))
                h.addWidget(ci)
                cancel_btn = QPushButton("Cancel", cell)
                cancel_btn.setEnabled(self._principal.has(Permission.APPOINTMENTS_CANCEL))
                cancel_btn.clicked.connect(lambda _=False, aid=a.id: self._on_cancel(aid))
                h.addWidget(cancel_btn)
            self._day_table.setCellWidget(r, 6, cell)

    # ----------------------------------------------------------- queue tab
    def _build_queue_tab(self, w: QWidget) -> None:
        v = QVBoxLayout(w)
        v.setSpacing(Spacing.S3)
        bar = QHBoxLayout()
        bar.setSpacing(Spacing.S2)
        bar.addWidget(QLabel("Waiting queue", w))
        bar.addStretch(1)
        self._walkin_btn = QPushButton("+ Walk-in", w)
        self._walkin_btn.setProperty("variant", "primary")
        self._walkin_btn.clicked.connect(self._on_walkin)
        self._walkin_btn.setVisible(self._principal.has(Permission.QUEUE_MANAGE))
        bar.addWidget(self._walkin_btn)
        self._refresh_q_btn = QPushButton("Refresh", w)
        self._refresh_q_btn.clicked.connect(self._reload_queue)
        bar.addWidget(self._refresh_q_btn)
        v.addLayout(bar)

        self._queue_table = QTableWidget(0, 7, w)
        self._queue_table.setObjectName("DpDataTable")
        self._queue_table.setHorizontalHeaderLabels(["#", "Patient", "Phone", "Dentist", "Wait", "Status", "Actions"])
        self._queue_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._queue_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._queue_table.verticalHeader().setVisible(False)
        hh = self._queue_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        v.addWidget(self._queue_table, 1)

    def _reload_queue(self) -> None:
        if not self._principal.has(Permission.QUEUE_MANAGE):
            self._queue_table.setRowCount(0)
            return
        with UnitOfWork(self._session_factory) as uow:
            queue = appointment_service.list_queue(uow.session, self._principal)
            uow.commit()
        self._queue_table.setRowCount(0)
        for q in queue:
            r = self._queue_table.rowCount()
            self._queue_table.insertRow(r)
            self._queue_table.setItem(r, 0, QTableWidgetItem(str(q.position or r + 1)))
            self._queue_table.setItem(r, 1, QTableWidgetItem(q.patient_name))
            self._queue_table.setItem(r, 2, QTableWidgetItem(q.patient_phone))
            self._queue_table.setItem(r, 3, QTableWidgetItem(q.dentist_name))
            wait_str = f"{q.wait_minutes}m"
            self._queue_table.setItem(r, 4, QTableWidgetItem(wait_str))
            status_item = QTableWidgetItem(q.status.replace("_", " ").title())
            color = STATUS_COLOR.get(q.status, "")
            if color:
                from PySide6.QtGui import QColor
                status_item.setForeground(QColor(color))
            self._queue_table.setItem(r, 5, status_item)
            cell = QWidget(self._queue_table)
            h = QHBoxLayout(cell)
            h.setContentsMargins(Spacing.S1, Spacing.S1, Spacing.S1, Spacing.S1)
            h.setSpacing(Spacing.S1)
            if q.status == "waiting":
                start = QPushButton("Start", cell)
                start.setProperty("variant", "primary")
                start.clicked.connect(lambda _=False, qid=q.id: self._on_start(qid))
                h.addWidget(start)
                rm = QPushButton("No-show", cell)
                rm.clicked.connect(lambda _=False, qid=q.id: self._on_remove(qid, "no_show"))
                h.addWidget(rm)
            elif q.status == "with_dentist":
                finish = QPushButton("Finish", cell)
                finish.setProperty("variant", "primary")
                finish.clicked.connect(lambda _=False, qid=q.id: self._on_finish(qid))
                h.addWidget(finish)
            else:
                done = QLabel("—", cell)
                done.setAlignment(Qt.AlignCenter)
                h.addWidget(done)
            self._queue_table.setCellWidget(r, 6, cell)

    # --------------------------------------------------------------- events
    def _on_new(self) -> None:
        qd = self._date_edit.date()
        initial = dt.date(qd.year(), qd.month(), qd.day())
        dlg = AppointmentDialog(self._session_factory, self._principal, initial_date=initial, parent=self)
        if dlg.exec():
            self._reload_day()

    def _on_edit(self, appt_id: int) -> None:
        with UnitOfWork(self._session_factory) as uow:
            a = appointment_service.get_appointment(uow.session, self._principal, appt_id)
            uow.commit()
        dlg = AppointmentDialog(self._session_factory, self._principal, appointment=a, parent=self)
        if dlg.exec():
            self._reload_day()

    def _on_check_in(self, appt_id: int) -> None:
        from PySide6.QtWidgets import QMessageBox
        try:
            with UnitOfWork(self._session_factory) as uow:
                appointment_service.check_in_appointment(uow.session, self._principal, appt_id)
                uow.commit()
        except (DentivaError, ValidationError) as e:
            QMessageBox.warning(self, "Cannot check in", e.user_message)
            return
        self._reload_day()
        self._reload_queue()
        self._tabs.setCurrentIndex(1)  # switch to queue

    def _on_cancel(self, appt_id: int) -> None:
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        reason, ok = QInputDialog.getText(self, "Cancel appointment", "Reason (optional):")
        if not ok:
            return
        try:
            with UnitOfWork(self._session_factory) as uow:
                appointment_service.cancel_appointment(uow.session, self._principal, appt_id, reason=reason)
                uow.commit()
        except Exception as e:
            QMessageBox.warning(self, "Cancel failed", getattr(e, "user_message", str(e)))
            return
        self._reload_day()

    def _on_walkin(self) -> None:
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        # Quick-pick a patient; for now ask for patient id by name via a simple
        # combo chooser.
        with UnitOfWork(self._session_factory) as uow:
            patients = patient_service.list_patients(uow.session, self._principal, limit=500)
        if not patients:
            QMessageBox.information(self, "No patients", "Add a patient first.")
            return
        # Build a simple selection dialog using QInputDialog with items.
        items = [f"{p.name} — {p.patient_code}" for p in patients]
        name, ok = QInputDialog.getItem(self, "Walk-in patient", "Select patient:", items, 0, False)
        if not ok:
            return
        idx = items.index(name)
        pid = patients[idx].id
        try:
            with UnitOfWork(self._session_factory) as uow:
                appointment_service.walk_in(uow.session, self._principal, pid)
                uow.commit()
        except Exception as e:
            QMessageBox.warning(self, "Walk-in failed", getattr(e, "user_message", str(e)))
            return
        self._reload_queue()
        self._tabs.setCurrentIndex(1)

    def _on_start(self, qid: int) -> None:
        try:
            with UnitOfWork(self._session_factory) as uow:
                from dentiva.models import Patient, Visit
                from dentiva.services.visit_service import get_visit
                _q, vid = appointment_service.start_service(uow.session, self._principal, qid)
                v = uow.session.get(Visit, vid)
                patient_obj = uow.session.get(Patient, v.patient_id) if v is not None else None
                visit_summary = get_visit(uow.session, self._principal, vid)
                uow.commit()
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Cannot start", getattr(e, "user_message", str(e)))
            return
        self._reload_queue()
        self._reload_day()
        if patient_obj is not None:
            from dentiva.ui.dialogs.visit_dialog import VisitDialog
            dlg = VisitDialog(
                self._session_factory, self._principal, patient_obj,
                visit=visit_summary, parent=self,
            )
            dlg.exec()
            self._reload_queue()
            self._reload_day()
        else:
            mw = self.window()
            show = getattr(mw, "show_message", None)
            if callable(show):
                show(f"Visit started (id={vid}).", timeout=3000)

    def _on_finish(self, qid: int) -> None:
        try:
            with UnitOfWork(self._session_factory) as uow:
                appointment_service.finish_service(uow.session, self._principal, qid)
                uow.commit()
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Cannot finish", getattr(e, "user_message", str(e)))
            return
        self._reload_queue()
        self._reload_day()

    def _on_remove(self, qid: int, reason: str = "no_show") -> None:
        try:
            with UnitOfWork(self._session_factory) as uow:
                appointment_service.remove_from_queue(uow.session, self._principal, qid, reason=reason)
                uow.commit()
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Remove failed", getattr(e, "user_message", str(e)))
            return
        self._reload_queue()
