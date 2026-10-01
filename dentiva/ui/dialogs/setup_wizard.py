"""First-run setup wizard (multi-page):

    1. Welcome
    2. Clinic profile (name, address, phone, email, logo)
    3. Dentists (add one or more dentists; name, designations, qualifications)
    4. Administrator (username, password, confirm password)
    5. Finish

Each page validates its input before allowing Next. The entire setup runs in a
single transaction via :func:`dentiva.services.setup_service.run_setup` so
partial failures never leave the database half-configured.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from dentiva import __product_name__
from dentiva.core.errors import DentivaError, ValidationError
from dentiva.core.validators import validate_email, validate_phone
from dentiva.db.seed import DEFAULT_DESIGNATIONS
from dentiva.services import setup_service

log = logging.getLogger(__name__)


@dataclass
class _DentistDraft:
    name: str = ""
    designations: list[str] = field(default_factory=list)
    qualifications: str = ""
    certifications: str = ""
    registration_no: str = ""
    phone: str = ""
    email: str = ""
    signature_path: str = ""
    photo_path: str = ""
    notes: str = ""


class WelcomePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle(f"Welcome to {__product_name__}")
        self.setSubTitle("Let's set up your dental clinic. This will take a couple of minutes.")
        v = QVBoxLayout(self)
        intro = QLabel(
            "The wizard will ask for:\n"
            "  • your clinic name, logo, and contact details;\n"
            "  • one or more dentists (their qualifications, certifications, signature);\n"
            "  • an administrator username and password for logging in.\n\n"
            "You can change all of this later from Settings."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#475467;")
        v.addWidget(intro)


class ClinicPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Clinic information")
        self.setSubTitle("This appears on prescriptions, invoices, and receipts.")
        form = QFormLayout(self)
        self._name_edit = QLineEdit(self)
        self._name_edit.setPlaceholderText("e.g. Pro Dental Care")
        self._tagline_edit = QLineEdit(self)
        self._tagline_edit.setPlaceholderText("Optional tagline")
        self._address_edit = QTextEdit(self)
        self._address_edit.setPlaceholderText("Clinic address")
        self._address_edit.setFixedHeight(72)
        self._phone_edit = QLineEdit(self)
        self._phone_edit.setPlaceholderText("01XXXXXXXX or +8801XXXXXXXX")
        self._email_edit = QLineEdit(self)
        self._email_edit.setPlaceholderText("clinic@example.com")
        self._footer_edit = QTextEdit(self)
        self._footer_edit.setPlaceholderText("Optional prescription footer message")
        self._footer_edit.setFixedHeight(60)
        # Logo picker
        self._logo_row = QWidget(self)
        logo_lay = QHBoxLayout(self._logo_row)
        logo_lay.setContentsMargins(0, 0, 0, 0)
        logo_lbl = QLabel("Logo:")
        self._logo_path = QLineEdit(self._logo_row)
        self._logo_path.setReadOnly(True)
        self._logo_btn = QPushButton("Browse…", self._logo_row)
        self._logo_btn.clicked.connect(self._pick_logo)
        self._logo_clear = QPushButton("Clear", self._logo_row)
        self._logo_clear.clicked.connect(lambda: self._logo_path.setText(""))
        logo_lay.addWidget(logo_lbl)
        logo_lay.addWidget(self._logo_path, 1)
        logo_lay.addWidget(self._logo_btn)
        logo_lay.addWidget(self._logo_clear)

        form.addRow("Clinic name *", self._name_edit)
        form.addRow("Tagline", self._tagline_edit)
        form.addRow("Address", self._address_edit)
        form.addRow("Phone", self._phone_edit)
        form.addRow("Email", self._email_edit)
        form.addRow("Prescription footer", self._footer_edit)
        form.addRow("", self._logo_row)

        self._name_error = QLabel("", self)
        self._name_error.setStyleSheet("color:#F04438;")
        form.addRow("", self._name_error)

        self.registerField("clinic_name*", self._name_edit)

    def _pick_logo(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        fname, _ = QFileDialog.getOpenFileName(self, "Select clinic logo", "",
                                               "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if fname:
            self._logo_path.setText(fname)

    def validatePage(self) -> bool:
        name = self._name_edit.text().strip()
        if not name:
            self._name_error.setText("Clinic name is required.")
            return False
        try:
            validate_phone(self._phone_edit.text(), "phone")
            validate_email(self._email_edit.text(), "email")
        except ValidationError as e:
            self._name_error.setText(e.user_message)
            return False
        self._name_error.setText("")
        return True

    def data(self) -> dict:
        return {
            "clinic_name": self._name_edit.text().strip(),
            "clinic_tagline": self._tagline_edit.text().strip(),
            "clinic_address": self._address_edit.toPlainText().strip(),
            "clinic_phone": self._phone_edit.text().strip(),
            "clinic_email": self._email_edit.text().strip(),
            "prescription_footer": self._footer_edit.toPlainText().strip(),
            "clinic_logo_path": self._logo_path.text().strip(),
        }


class _DentistEditor(QDialog):
    """Sub-dialog to add/edit a dentist during setup."""

    def __init__(self, draft: _DentistDraft | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Dentist")
        self.setMinimumWidth(480)
        self._draft = draft or _DentistDraft()
        v = QVBoxLayout(self)

        form = QFormLayout()
        self._name = QLineEdit(self._draft.name)
        self._phone = QLineEdit(self._draft.phone)
        self._email = QLineEdit(self._draft.email)
        self._reg = QLineEdit(self._draft.registration_no)
        self._desig_combo = QComboBox(self)
        self._desig_combo.setEditable(True)
        for d in DEFAULT_DESIGNATIONS:
            self._desig_combo.addItem(d)
        self._desig_list = QListWidget(self)
        self._desig_list.setFixedHeight(90)
        for d in self._draft.designations:
            self._desig_list.addItem(QListWidgetItem(d))
        add_desig_btn = QPushButton("Add designation", self)
        add_desig_btn.clicked.connect(self._add_desig)
        remove_desig_btn = QPushButton("Remove selected", self)
        remove_desig_btn.clicked.connect(self._remove_desig)
        desig_row = QHBoxLayout()
        desig_row.addWidget(self._desig_combo, 1)
        desig_row.addWidget(add_desig_btn)
        desig_row.addWidget(remove_desig_btn)
        self._qual = QTextEdit(self._draft.qualifications)
        self._qual.setFixedHeight(60)
        self._cert = QTextEdit(self._draft.certifications)
        self._cert.setFixedHeight(60)
        self._notes = QTextEdit(self._draft.notes)
        self._notes.setFixedHeight(50)

        form.addRow("Name *", self._name)
        form.addRow("Designations", self._desig_list)
        form.addRow("", self._wrap(desig_row))
        form.addRow("Qualifications", self._qual)
        form.addRow("Certifications", self._cert)
        form.addRow("Reg. #", self._reg)
        form.addRow("Phone", self._phone)
        form.addRow("Email", self._email)
        form.addRow("Notes", self._notes)
        v.addLayout(form)

        self._error = QLabel("", self)
        self._error.setStyleSheet("color:#F04438;")
        v.addWidget(self._error)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Save", self)
        ok.setProperty("variant", "primary")
        ok.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        v.addLayout(btns)

    def _wrap(self, layout) -> QWidget:
        w = QWidget(self)
        w.setLayout(layout)
        return w

    def _add_desig(self) -> None:
        text = self._desig_combo.currentText().strip()
        if not text:
            return
        for i in range(self._desig_list.count()):
            if self._desig_list.item(i).text() == text:
                return
        self._desig_list.addItem(QListWidgetItem(text))

    def _remove_desig(self) -> None:
        for item in self._desig_list.selectedItems():
            self._desig_list.takeItem(self._desig_list.row(item))

    def _accept(self) -> None:
        if not self._name.text().strip():
            self._error.setText("Dentist name is required.")
            return
        try:
            if self._phone.text().strip():
                from dentiva.core.validators import validate_phone as vp
                vp(self._phone.text(), "phone")
            if self._email.text().strip():
                validate_email(self._email.text(), "email")
        except ValidationError as e:
            self._error.setText(e.user_message)
            return
        self._draft = _DentistDraft(
            name=self._name.text().strip(),
            designations=[self._desig_list.item(i).text() for i in range(self._desig_list.count())],
            qualifications=self._qual.toPlainText().strip(),
            certifications=self._cert.toPlainText().strip(),
            registration_no=self._reg.text().strip(),
            phone=self._phone.text().strip(),
            email=self._email.text().strip(),
            notes=self._notes.toPlainText().strip(),
        )
        self.accept()

    def draft(self) -> _DentistDraft:
        return self._draft


class DentistsPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Dentists")
        self.setSubTitle("Add at least one dentist. You can add more and edit existing ones later in Settings.")
        v = QVBoxLayout(self)
        self._list = QListWidget(self)
        v.addWidget(self._list, 1)
        row = QHBoxLayout()
        add = QPushButton("Add dentist…", self)
        add.clicked.connect(self._add)
        edit = QPushButton("Edit selected…", self)
        edit.clicked.connect(self._edit)
        remove = QPushButton("Remove selected", self)
        remove.clicked.connect(self._remove)
        row.addWidget(add)
        row.addWidget(edit)
        row.addWidget(remove)
        row.addStretch(1)
        v.addLayout(row)
        self._error = QLabel("", self)
        self._error.setStyleSheet("color:#F04438;")
        v.addWidget(self._error)
        self._dentists: list[_DentistDraft] = []
        self._refresh()

    def _refresh(self) -> None:
        self._list.clear()
        for d in self._dentists:
            desig = ", ".join(d.designations) if d.designations else ""
            label = f"{d.name}" + (f" — {desig}" if desig else "")
            self._list.addItem(QListWidgetItem(label))

    def _add(self) -> None:
        dlg = _DentistEditor(parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._dentists.append(dlg.draft())
            self._refresh()
            self.completeChanged.emit()

    def _edit(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        dlg = _DentistEditor(draft=self._dentists[row], parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._dentists[row] = dlg.draft()
            self._refresh()

    def _remove(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            del self._dentists[row]
            self._refresh()
            self.completeChanged.emit()

    def isComplete(self) -> bool:
        return len(self._dentists) > 0

    def validatePage(self) -> bool:
        if not self._dentists:
            self._error.setText("Please add at least one dentist.")
            return False
        self._error.setText("")
        return True

    def dentists(self) -> list[_DentistDraft]:
        return list(self._dentists)


class AdminPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Administrator account")
        self.setSubTitle("You will use this to sign in to Dentiva Pro.")
        form = QFormLayout(self)
        self._display = QLineEdit(self)
        self._display.setPlaceholderText("Your name (e.g. Dr. Rahman)")
        self._user = QLineEdit(self)
        self._user.setPlaceholderText("3–32 letters/numbers/._")
        self._pass = QLineEdit(self)
        self._pass.setEchoMode(QLineEdit.Password)
        self._pass.setPlaceholderText("At least 6 characters")
        self._pass2 = QLineEdit(self)
        self._pass2.setEchoMode(QLineEdit.Password)
        self._pass2.setPlaceholderText("Confirm password")
        form.addRow("Display name", self._display)
        form.addRow("Username *", self._user)
        form.addRow("Password *", self._pass)
        form.addRow("Confirm password *", self._pass2)
        self._error = QLabel("", self)
        self._error.setStyleSheet("color:#F04438;")
        self._error.setWordWrap(True)
        form.addRow("", self._error)
        self.registerField("admin_user*", self._user)

    def validatePage(self) -> bool:
        from dentiva.core.validators import (
            validate_password_strength,
            validate_username,
        )
        try:
            validate_username(self._user.text())
            validate_password_strength(self._pass.text())
        except ValidationError as e:
            self._error.setText(e.user_message)
            return False
        if self._pass.text() != self._pass2.text():
            self._error.setText("Passwords do not match.")
            return False
        self._error.setText("")
        return True

    def data(self) -> dict:
        return {
            "admin_display_name": self._display.text().strip(),
            "admin_username": self._user.text().strip(),
            "admin_password": self._pass.text(),
        }


class SetupWizard(QWizard):
    def __init__(self, session_factory, parent=None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self.setWindowTitle(f"Set up {__product_name__}")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.IndependentPages, False)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setMinimumSize(640, 520)

        self._welcome = WelcomePage()
        self._clinic = ClinicPage()
        self._dentists = DentistsPage()
        self._admin = AdminPage()

        self.addPage(self._welcome)
        self.addPage(self._clinic)
        self.addPage(self._dentists)
        self.addPage(self._admin)

        self.button(QWizard.FinishButton).clicked.connect(self._on_finish)
        self._success = False

    def _on_finish(self) -> None:
        clinic = self._clinic.data()
        admin = self._admin.data()
        dentist_drafts = self._dentists.dentists()
        dentists = [
            setup_service.DentistSetupInput(
                name=d.name,
                designations=d.designations,
                qualifications=d.qualifications,
                certifications=d.certifications,
                registration_no=d.registration_no,
                phone=d.phone,
                email=d.email,
                notes=d.notes,
            )
            for d in dentist_drafts
        ]
        data = setup_service.SetupInput(
            **clinic,
            **admin,
            dentists=dentists,
        )
        from dentiva.core.unit_of_work import UnitOfWork
        try:
            with UnitOfWork(self._session_factory) as uow:
                setup_service.run_setup(uow.session, data)
                uow.commit()
            self._success = True
            QMessageBox.information(self, "Setup complete",
                                    "Dentiva Pro is ready. You can now sign in with your administrator account.")
        except DentivaError as e:
            QMessageBox.critical(self, "Setup failed", e.user_message)
            # Prevent the wizard from closing.
            self.button(QWizard.FinishButton).setEnabled(True)
            self.restart()  # return to page 1 in a simple way (values preserved below)
        except Exception as e:  # pragma: no cover - defensive
            log.exception("Unexpected setup failure: %s", e)
            QMessageBox.critical(self, "Setup failed",
                                 "An unexpected error occurred. Check the logs for details.")

    def setup_succeeded(self) -> bool:
        return self._success
