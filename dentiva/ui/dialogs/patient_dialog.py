"""Patient dialog: create/edit patient with validation.

Exposes :class:`PatientFormDialog` which collects input from the user and
calls back into :mod:`dentiva.services.patient_service`. A typed
confirmation dialog for soft-delete is also provided.
"""
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from dentiva.core.errors import DentivaError, ValidationError
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import patient_service

if TYPE_CHECKING:

    from dentiva.core.permissions import Principal


class PatientFormDialog(QDialog):
    """Create or edit a patient."""

    def __init__(
        self,
        session_factory,
        principal: Principal,
        *,
        patient=None,  # Patient instance or None for create
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal
        self._patient = patient
        self.setMinimumWidth(560)
        self.setWindowTitle("Edit patient" if patient else "New patient")
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self._code = QLineEdit(self)
        self._code.setPlaceholderText("Auto-assigned (e.g. P-000001)")
        self._code.setToolTip("Leave blank to auto-generate.")
        form.addRow("Patient code", self._code)

        self._name = QLineEdit(self)
        form.addRow("Full name *", self._name)

        self._dob = QDateEdit(self)
        self._dob.setCalendarPopup(True)
        self._dob.setDisplayFormat("yyyy-MM-dd")
        self._dob.setSpecialValueText(" ")
        self._dob.setMinimumDate(QDate(1900, 1, 1))
        self._dob.setMaximumDate(QDate.currentDate())
        # Start with no DOB chosen (show the special-value placeholder).
        self._dob.setDate(self._dob.minimumDate())
        self._dob.clear()
        self._dob_set = False  # True once user picks a date
        self._dob.dateChanged.connect(self._on_dob_changed)
        form.addRow("Date of birth", self._dob)

        self._gender = QComboBox(self)
        self._gender.addItem("", "")
        self._gender.addItem("Male", "Male")
        self._gender.addItem("Female", "Female")
        self._gender.addItem("Other", "Other")
        form.addRow("Gender", self._gender)

        self._blood = QComboBox(self)
        self._blood.addItem("", "")
        for bg in ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"):
            self._blood.addItem(bg, bg)
        form.addRow("Blood group", self._blood)

        self._phone = QLineEdit(self)
        self._phone.setPlaceholderText("01XXXXXXXXX")
        form.addRow("Phone", self._phone)

        self._emergency_phone = QLineEdit(self)
        self._emergency_phone.setPlaceholderText("01XXXXXXXXX")
        form.addRow("Emergency phone", self._emergency_phone)

        self._email = QLineEdit(self)
        form.addRow("Email", self._email)

        self._address = QPlainTextEdit(self)
        self._address.setFixedHeight(60)
        form.addRow("Address", self._address)

        self._chief = QPlainTextEdit(self)
        self._chief.setFixedHeight(50)
        form.addRow("Chief complaint", self._chief)

        self._history = QPlainTextEdit(self)
        self._history.setFixedHeight(60)
        form.addRow("Medical history", self._history)

        self._allergies = QLineEdit(self)
        form.addRow("Allergies", self._allergies)

        self._notes = QPlainTextEdit(self)
        self._notes.setFixedHeight(50)
        form.addRow("Notes", self._notes)

        layout.addLayout(form)

        self._error_label = QLabel("", self)
        self._error_label.setObjectName("DpFieldError")
        self._error_label.setWordWrap(True)
        layout.addWidget(self._error_label)

        buttons_row = QHBoxLayout()
        buttons_row.addStretch(1)
        self._bb = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, parent=self
        )
        self._bb.accepted.connect(self._save)
        self._bb.rejected.connect(self.reject)
        buttons_row.addWidget(self._bb)
        layout.addLayout(buttons_row)

        # Populate fields when editing
        if patient is not None:
            self._code.setText(patient.patient_code)
            self._code.setReadOnly(True)  # don't change code on edit
            self._name.setText(patient.name)
            if patient.dob is not None:
                self._dob.setDate(QDate(patient.dob.year, patient.dob.month, patient.dob.day))
                self._dob_set = True
            idx = self._gender.findData(patient.gender)
            if idx >= 0:
                self._gender.setCurrentIndex(idx)
            else:
                self._gender.setEditText(patient.gender or "")
            bidx = self._blood.findData(patient.blood_group)
            if bidx >= 0:
                self._blood.setCurrentIndex(bidx)
            self._phone.setText(patient.phone)
            self._emergency_phone.setText(patient.emergency_phone)
            self._email.setText(patient.email)
            self._address.setPlainText(patient.address)
            self._chief.setPlainText(patient.chief_complaint)
            self._history.setPlainText(patient.medical_history)
            self._allergies.setText(patient.allergies)
            self._notes.setPlainText(patient.notes)
        else:
            self._name.setFocus()

    def _on_dob_changed(self) -> None:
        # Treat any date ≥ 1901 as explicitly set (below that is the
        # sentinel "empty" value from minimumDate).
        d = self._dob.date()
        self._dob_set = d.year() > 1900

    # ----------------------------------------------------------------- save
    def _save(self) -> None:
        self._error_label.setText("")
        dob_val = None
        if getattr(self, "_dob_set", False):
            qd = self._dob.date()
            if qd.isValid() and qd.year() > 1900:
                dob_val = self._qdate_to_date(qd)
        data = patient_service.PatientInput(
            name=self._name.text(),
            dob=dob_val,
            gender=self._gender.currentData() or (self._gender.currentText() if self._gender.isEditable() else ""),
            blood_group=self._blood.currentData() or "",
            address=self._address.toPlainText(),
            phone=self._phone.text(),
            emergency_phone=self._emergency_phone.text(),
            email=self._email.text(),
            patient_code=self._code.text(),
            chief_complaint=self._chief.toPlainText(),
            medical_history=self._history.toPlainText(),
            allergies=self._allergies.text(),
            notes=self._notes.toPlainText(),
        )
        try:
            with UnitOfWork(self._session_factory) as uow:
                if self._patient is None:
                    patient_service.create_patient(uow.session, self._principal, data)
                else:
                    patient_service.update_patient(uow.session, self._principal, self._patient.id, data)
                uow.commit()
        except ValidationError as e:
            self._error_label.setText(e.user_message)
            return
        except DentivaError as e:
            self._error_label.setText(e.user_message)
            return
        self.accept()

    @staticmethod
    def _qdate_to_date(qd: QDate) -> dt.date:
        return dt.date(qd.year(), qd.month(), qd.day())


class ConfirmDeleteDialog(QDialog):
    """Asks the user to type 'DELETE P-XXXXXX' to confirm patient deletion."""

    def __init__(self, patient, parent=None) -> None:
        super().__init__(parent)
        self._expected = f"DELETE {patient.patient_code}"
        self.setWindowTitle("Delete patient")
        self.setModal(True)
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        warn = QLabel(
            f"<b>Delete patient?</b><br>"
            f"You are about to permanently remove <b>{patient.name}</b> "
            f"(code {patient.patient_code}) from active records. This action "
            f"is logged and cannot be undone from the UI.",
            self,
        )
        warn.setWordWrap(True)
        v.addWidget(warn)
        prompt = QLabel(
            f"To confirm, type <b>{self._expected}</b> in the box below:", self
        )
        prompt.setWordWrap(True)
        v.addWidget(prompt)
        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText(self._expected)
        v.addWidget(self._edit)
        self._err = QLabel("", self)
        self._err.setObjectName("DpFieldError")
        self._err.setWordWrap(True)
        v.addWidget(self._err)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        self._delete_btn = QPushButton("Delete patient", self)
        self._delete_btn.setProperty("variant", "destructive")
        self._delete_btn.clicked.connect(self._confirm)
        btns.addWidget(cancel)
        btns.addWidget(self._delete_btn)
        v.addLayout(btns)

    def confirmation_text(self) -> str:
        return self._edit.text()

    def _confirm(self) -> None:
        if self._edit.text().strip().upper() != self._expected:
            self._err.setText(f"Please type '{self._expected}' to confirm.")
            return
        self.accept()


def confirm_delete_patient(parent, session_factory, principal, patient) -> bool:
    """Run the typed-confirmation dialog and, if accepted, perform the
    soft-delete via the service. Returns True on success."""
    dlg = ConfirmDeleteDialog(patient, parent=parent)
    if dlg.exec() != QDialog.Accepted:
        return False
    try:
        with UnitOfWork(session_factory) as uow:
            patient_service.delete_patient(
                uow.session, principal, patient.id,
                confirmation_text=dlg.confirmation_text(),
            )
            uow.commit()
    except (DentivaError, ValidationError) as e:
        QMessageBox.warning(parent, "Cannot delete", e.user_message)
        return False
    QMessageBox.information(parent, "Patient deleted",
                            f"{patient.name} ({patient.patient_code}) has been deleted.")
    return True
