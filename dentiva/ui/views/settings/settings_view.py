# mypy: disable-error-code="arg-type, attr-defined, union-attr"
"""Settings view — clinic profile, notifications, printing defaults."""
from __future__ import annotations

from dentiva.core.errors import DentivaError, ValidationError
from dentiva.core.permissions import Permission
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.models import ClinicProfile
from dentiva.services import notification_service
from dentiva.ui.design_tokens import Spacing
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class _ClinicTab(QWidget):
    def __init__(self, session_factory, principal, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        self._can_edit = principal.has(Permission.CLINIC_PROFILE_MANAGE)
        v = QVBoxLayout(self)
        form = QFormLayout()
        self._name = QLineEdit(self)
        self._phone = QLineEdit(self)
        self._email = QLineEdit(self)
        self._address = QLineEdit(self)
        self._tagline = QLineEdit(self)
        self._footer = QTextEdit(self)
        self._footer.setFixedHeight(80)
        self._logo_path = QLineEdit(self)
        self._logo_path.setReadOnly(True)
        logo_row = QHBoxLayout()
        browse = QPushButton("Browse…", self)
        browse.clicked.connect(self._browse_logo)
        clear_logo = QPushButton("Clear", self)
        clear_logo.clicked.connect(self._clear_logo)
        logo_row.addWidget(self._logo_path, 1)
        logo_row.addWidget(browse)
        logo_row.addWidget(clear_logo)
        logo_wrap = QWidget(self)
        logo_wrap.setLayout(logo_row)
        form.addRow("Clinic name", self._name)
        form.addRow("Phone", self._phone)
        form.addRow("Email", self._email)
        form.addRow("Address", self._address)
        form.addRow("Tagline", self._tagline)
        form.addRow("Logo", logo_wrap)
        form.addRow("Prescription footer", self._footer)
        for w in (
            self._name, self._phone, self._email, self._address, self._tagline,
            self._footer, browse, clear_logo,
        ):
            w.setEnabled(self._can_edit)
        v.addLayout(form)
        save = QPushButton("Save changes", self)
        save.setProperty("variant", "primary")
        save.clicked.connect(self._save)
        save.setEnabled(self._can_edit)
        v.addWidget(save)
        v.addStretch(1)
        self._status = QLabel("", self)
        self._status.setObjectName("DpFieldError")
        v.addWidget(self._status)
        self._load()

    def _load(self) -> None:
        with UnitOfWork(self._sf) as uow:
            cp = uow.session.query(ClinicProfile).first()
        if cp is None:
            return
        self._name.setText(cp.name or "")
        self._phone.setText(cp.phone or "")
        self._email.setText(cp.email or "")
        self._address.setText(cp.address or "")
        self._tagline.setText(cp.tagline or "")
        self._footer.setPlainText(cp.prescription_footer or "")
        self._logo_path.setText(cp.logo_path or "")

    def _browse_logo(self) -> None:
        fn, _ = QFileDialog.getOpenFileName(
            self, "Clinic logo", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)",
        )
        if not fn:
            return
        try:
            with UnitOfWork(self._sf) as uow:
                from dentiva.services import clinic_service
                saved = clinic_service.save_logo_from_path(fn)
                cp = uow.session.query(ClinicProfile).first()
                if cp is not None:
                    cp.logo_path = saved
                uow.commit()
        except (DentivaError, ValidationError) as e:
            self._status.setText(e.user_message)
            return
        self._logo_path.setText(saved)
        self._status.setText("Logo saved.")

    def _clear_logo(self) -> None:
        with UnitOfWork(self._sf) as uow:
            cp = uow.session.query(ClinicProfile).first()
            if cp is not None:
                cp.logo_path = ""
            uow.commit()
        self._logo_path.setText("")

    def _save(self) -> None:
        self._status.setText("")
        try:
            with UnitOfWork(self._sf) as uow:
                from dentiva.services import clinic_service
                existing_logo = ""
                cp = uow.session.query(ClinicProfile).first()
                if cp is not None:
                    existing_logo = cp.logo_path or ""
                clinic_service.setup_clinic(
                    uow.session,
                    name=self._name.text(),
                    phone=self._phone.text(),
                    email=self._email.text(),
                    address=self._address.text(),
                    tagline=self._tagline.text(),
                    logo_path=existing_logo,
                    prescription_footer=self._footer.toPlainText(),
                )
                uow.commit()
        except (DentivaError, ValidationError) as e:
            self._status.setText(e.user_message)
            return
        self._status.setText("Clinic profile saved.")


class _NotificationsTab(QWidget):
    def __init__(self, session_factory, principal, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        self._can_edit = principal.has(Permission.NOTIFICATIONS_MANAGE) or principal.is_superuser
        v = QVBoxLayout(self)
        form = QFormLayout()
        self._appt_enabled = QCheckBox("Enable upcoming-appointment reminders", self)
        self._appt_lead = QSpinBox(self)
        self._appt_lead.setRange(5, 24 * 60)
        self._appt_lead.setSuffix(" min")
        self._summary_enabled = QCheckBox("Show today's appointment summary on first open of the day", self)
        self._low_stock_enabled = QCheckBox("Show low-stock alerts", self)
        self._overdue_enabled = QCheckBox("Show overdue-invoice alerts", self)
        self._overdue_days = QSpinBox(self)
        self._overdue_days.setRange(0, 365)
        self._overdue_days.setSuffix(" day(s)")
        form.addRow(self._appt_enabled)
        form.addRow("Remind before", self._appt_lead)
        form.addRow(self._summary_enabled)
        form.addRow(self._low_stock_enabled)
        form.addRow(self._overdue_enabled)
        form.addRow("Overdue threshold", self._overdue_days)
        for w in self.findChildren(QWidget):
            w.setEnabled(self._can_edit)
        v.addLayout(form)
        save = QPushButton("Save", self)
        save.setProperty("variant", "primary")
        save.clicked.connect(self._save)
        save.setEnabled(self._can_edit)
        v.addWidget(save)
        v.addStretch(1)
        self._status = QLabel("", self)
        self._status.setObjectName("DpFieldError")
        v.addWidget(self._status)
        self._load()

    def _load(self) -> None:
        with UnitOfWork(self._sf) as uow:
            self._appt_enabled.setChecked(
                bool(notification_service.get_setting(uow.session, "notif.appt_reminder.enabled", self._p))
            )
            self._appt_lead.setValue(
                int(notification_service.get_setting(uow.session, "notif.appt_reminder.lead_minutes", self._p))
            )
            self._summary_enabled.setChecked(
                bool(notification_service.get_setting(uow.session, "notif.today_summary.enabled", self._p))
            )
            self._low_stock_enabled.setChecked(
                bool(notification_service.get_setting(uow.session, "notif.low_stock.enabled", self._p))
            )
            self._overdue_enabled.setChecked(
                bool(notification_service.get_setting(uow.session, "notif.overdue_invoice.enabled", self._p))
            )
            self._overdue_days.setValue(
                int(notification_service.get_setting(uow.session, "notif.overdue_invoice.days", self._p))
            )
            uow.commit()

    def _save(self) -> None:
        with UnitOfWork(self._sf) as uow:
            notification_service.set_setting(uow.session, "notif.appt_reminder.enabled", self._appt_enabled.isChecked(), self._p)
            notification_service.set_setting(uow.session, "notif.appt_reminder.lead_minutes", self._appt_lead.value(), self._p)
            notification_service.set_setting(uow.session, "notif.today_summary.enabled", self._summary_enabled.isChecked(), self._p)
            notification_service.set_setting(uow.session, "notif.low_stock.enabled", self._low_stock_enabled.isChecked(), self._p)
            notification_service.set_setting(uow.session, "notif.overdue_invoice.enabled", self._overdue_enabled.isChecked(), self._p)
            notification_service.set_setting(uow.session, "notif.overdue_invoice.days", self._overdue_days.value(), self._p)
            uow.commit()
        self._status.setText("Notification preferences saved.")


class _PrintingTab(QWidget):
    def __init__(self, session_factory, principal, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        v = QVBoxLayout(self)
        info = QLabel(
            "Print defaults are used by the Print and PDF buttons in Prescription "
            "and Invoice dialogs. Paper size can be overridden per print.",
            self,
        )
        info.setWordWrap(True)
        v.addWidget(info)
        form = QFormLayout()
        self._rx_paper = QComboBox(self)
        self._inv_paper = QComboBox(self)
        for code, label in (
            ("a4", "A4"), ("a5", "A5"),
            ("thermal-80", "Thermal 80mm"), ("thermal-58", "Thermal 58mm"),
        ):
            self._rx_paper.addItem(label, code)
            self._inv_paper.addItem(label, code)
        form.addRow("Prescription default paper", self._rx_paper)
        form.addRow("Invoice default paper", self._inv_paper)
        v.addLayout(form)
        save = QPushButton("Save", self)
        save.setProperty("variant", "primary")
        save.clicked.connect(self._save)
        save.setEnabled(principal.has(Permission.PRINTERS_MANAGE) or principal.is_superuser)
        v.addWidget(save)
        v.addStretch(1)
        self._status = QLabel("", self)
        self._status.setObjectName("DpFieldError")
        v.addWidget(self._status)
        self._load()

    def _load(self) -> None:
        with UnitOfWork(self._sf) as uow:
            self._rx_paper.setCurrentIndex(self._rx_paper.findData(
                notification_service.get_setting(uow.session, "print.prescription.paper", self._p) or "a4"
            ))
            self._inv_paper.setCurrentIndex(self._inv_paper.findData(
                notification_service.get_setting(uow.session, "print.invoice.paper", self._p) or "a4"
            ))
            uow.commit()

    def _save(self) -> None:
        with UnitOfWork(self._sf) as uow:
            notification_service.set_setting(
                uow.session, "print.prescription.paper", self._rx_paper.currentData(), self._p,
            )
            notification_service.set_setting(
                uow.session, "print.invoice.paper", self._inv_paper.currentData(), self._p,
            )
            uow.commit()
        self._status.setText("Print defaults saved.")


class SettingsView(QWidget):
    def __init__(self, session_factory, principal, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.S4)
        title = QLabel("Settings", self)
        title.setObjectName("DpPageTitle")
        sub = QLabel("Clinic profile, notifications, and print defaults.", self)
        sub.setObjectName("DpPageSubtitle")
        root.addWidget(title)
        root.addWidget(sub)
        tabs = QTabWidget(self)
        tabs.addTab(_ClinicTab(session_factory, principal, self), "Clinic")
        tabs.addTab(_NotificationsTab(session_factory, principal, self), "Notifications")
        tabs.addTab(_PrintingTab(session_factory, principal, self), "Printing")
        root.addWidget(tabs, 1)

    def refresh(self) -> None:
        pass
