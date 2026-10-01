"""Appointment dialog — create / reschedule an appointment."""
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, QDateTime, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from dentiva.core.dates import local_now
from dentiva.core.errors import DentivaError, ValidationError
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import appointment_service, dentist_service, patient_service

if TYPE_CHECKING:

    from dentiva.core.permissions import Principal


DURATIONS = (5, 10, 15, 20, 30, 45, 60, 90)


class AppointmentDialog(QDialog):
    def __init__(
        self,
        session_factory,
        principal: Principal,
        *,
        appointment=None,   # AppointmentRow or None
        preselected_patient_id: int | None = None,
        preselected_dentist_id: int | None = None,
        initial_date: dt.date | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal
        self._appointment = appointment
        self.setMinimumWidth(480)
        self.setWindowTitle("Edit appointment" if appointment else "New appointment")
        self.setModal(True)

        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        # Patient — searchable combo (we'll use editable QComboBox with
        # name completion for speed).
        self._patient = QComboBox(self)
        self._patient.setEditable(True)
        self._patient.setInsertPolicy(QComboBox.NoInsert)
        self._patient.setMinimumWidth(320)
        form.addRow("Patient *", self._patient)

        self._dentist = QComboBox(self)
        self._dentist.addItem("— Unassigned —", None)
        form.addRow("Dentist", self._dentist)

        self._when = QDateTimeEdit(self)
        self._when.setCalendarPopup(True)
        self._when.setDisplayFormat("yyyy-MM-dd HH:mm")
        # Default to now rounded up to the next 15-minute slot.
        now_dt = local_now()
        minutes = ((now_dt.minute // 15) + 1) * 15
        if minutes >= 60:
            now_dt = now_dt.replace(second=0, microsecond=0) + dt.timedelta(hours=1)
            minutes = 0
        default_dt = now_dt.replace(minute=minutes, second=0, microsecond=0)
        self._when.setDateTime(QDateTime.fromString(default_dt.strftime("%Y-%m-%d %H:%M"), "yyyy-MM-dd HH:mm"))
        if initial_date is not None:
            self._when.setDate(QDate(initial_date.year, initial_date.month, initial_date.day))
            from PySide6.QtCore import QTime
            self._when.setTime(QTime(9, 0))
        form.addRow("Date & time *", self._when)

        self._duration = QSpinBox(self)
        self._duration.setRange(5, 480)
        self._duration.setSingleStep(5)
        self._duration.setSuffix(" min")
        self._duration.setValue(15)
        form.addRow("Duration", self._duration)

        self._reason = QLineEdit(self)
        self._reason.setPlaceholderText("Checkup, Filling, Scaling, …")
        form.addRow("Reason", self._reason)

        self._notes = QPlainTextEdit(self)
        self._notes.setFixedHeight(60)
        form.addRow("Notes", self._notes)

        root.addLayout(form)
        self._error = QLabel("", self)
        self._error.setObjectName("DpFieldError")
        self._error.setWordWrap(True)
        root.addWidget(self._error)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save", self)
        save.setProperty("variant", "primary")
        save.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(save)
        root.addLayout(btns)

        # Load patients/dentists
        self._load_patients(selected_id=(appointment.patient_id if appointment else preselected_patient_id))
        self._load_dentists(selected_id=(appointment.dentist_id if appointment else preselected_dentist_id))

        if appointment is not None:
            # Populate fields
            if appointment.scheduled_at is not None:
                qdt = QDateTime.fromString(appointment.scheduled_at.strftime("%Y-%m-%d %H:%M"), "yyyy-MM-dd HH:mm")
                self._when.setDateTime(qdt)
            self._duration.setValue(appointment.duration_minutes or 15)
            self._reason.setText(appointment.reason)
            self._notes.setPlainText(appointment.notes)

    # --------------------------------------------------------------- loads
    def _load_patients(self, *, selected_id: int | None = None) -> None:
        with UnitOfWork(self._session_factory) as uow:
            patients = patient_service.list_patients(uow.session, self._principal, limit=500)
        self._patient.clear()
        self._patient_id_map: dict[str, int] = {}
        for p in patients:
            label = f"{p.name} — {p.patient_code}"
            if p.phone:
                label += f" ({p.phone})"
            self._patient.addItem(label, p.id)
            self._patient_id_map[label] = p.id
        if selected_id is not None:
            idx = self._patient.findData(selected_id)
            if idx >= 0:
                self._patient.setCurrentIndex(idx)

    def _load_dentists(self, *, selected_id: int | None = None) -> None:
        with UnitOfWork(self._session_factory) as uow:
            dentists = dentist_service.list_dentists(uow.session, self._principal, include_inactive=False)
        for d in dentists:
            self._dentist.addItem(d.name, d.id)
        if selected_id is not None:
            idx = self._dentist.findData(selected_id)
            if idx >= 0:
                self._dentist.setCurrentIndex(idx)

    # --------------------------------------------------------------- save
    def _save(self) -> None:
        self._error.setText("")
        patient_id = self._patient.currentData()
        if not isinstance(patient_id, int):
            # Try to look up by typed text
            typed = self._patient.currentText().strip()
            if typed in self._patient_id_map:
                patient_id = self._patient_id_map[typed]
            else:
                self._error.setText("Please select a patient from the list.")
                return
        dt_qt = self._when.dateTime().toPython()
        if isinstance(dt_qt, dt.datetime):
            if dt_qt.tzinfo is not None:
                from dentiva.core.dates import TZ
                scheduled_at: dt.datetime = dt_qt.astimezone(TZ).replace(tzinfo=None)
            else:
                scheduled_at = dt_qt
        elif isinstance(dt_qt, dt.date):
            scheduled_at = dt.datetime.combine(dt_qt, dt.time())
        else:
            self._error.setText("Invalid date/time.")
            return
        data = appointment_service.AppointmentInput(
            patient_id=int(patient_id),
            dentist_id=self._dentist.currentData(),
            scheduled_at=scheduled_at,
            duration_minutes=self._duration.value(),
            reason=self._reason.text(),
            notes=self._notes.toPlainText(),
        )
        try:
            with UnitOfWork(self._session_factory) as uow:
                if self._appointment is None:
                    appointment_service.create_appointment(uow.session, self._principal, data)
                else:
                    appointment_service.update_appointment(uow.session, self._principal, self._appointment.id, data)
                uow.commit()
        except ValidationError as e:
            self._error.setText(e.user_message)
            return
        except DentivaError as e:
            self._error.setText(e.user_message)
            return
        self.accept()
