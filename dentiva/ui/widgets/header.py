"""Application header bar."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from dentiva import __product_name__
from dentiva.core.dates import format_datetime, now
from dentiva.ui.design_tokens import Shell, Spacing


class Header(QFrame):
    """Top header bar: brand, clinic name, date, notifications, user menu."""

    toggle_sidebar = Signal()
    logout_requested = Signal()
    lock_requested = Signal()
    notifications_requested = Signal()
    user_menu_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DpHeader")
        self.setFixedHeight(Shell.HEADER_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(Spacing.S4, 0, Spacing.S4, 0)
        layout.setSpacing(Spacing.S3)

        self._toggle_btn = QPushButton("☰", self)
        self._toggle_btn.setObjectName("DpIconButton")
        self._toggle_btn.setToolTip("Toggle sidebar (Ctrl+B)")
        self._toggle_btn.clicked.connect(self.toggle_sidebar.emit)
        layout.addWidget(self._toggle_btn)

        brand = QLabel(__product_name__, self)
        brand.setObjectName("DpBrandLabel")
        layout.addWidget(brand)

        self._clinic_label = QLabel("", self)
        self._clinic_label.setObjectName("DpClinicLabel")
        layout.addWidget(self._clinic_label)

        layout.addStretch(1)

        self._date_label = QLabel("", self)
        self._date_label.setObjectName("DpDateLabel")
        layout.addWidget(self._date_label)

        self._notif_btn = QPushButton("🔔", self)
        self._notif_btn.setObjectName("DpIconButton")
        self._notif_btn.setToolTip("Notifications")
        self._notif_btn.clicked.connect(self.notifications_requested.emit)
        layout.addWidget(self._notif_btn)

        self._user_btn = QPushButton("▼", self)
        self._user_btn.setObjectName("DpIconButton")
        self._user_btn.setToolTip("Account")
        self._user_btn.clicked.connect(self.user_menu_requested.emit)
        layout.addWidget(self._user_btn)

        self._lock_btn = QPushButton("🔒", self)
        self._lock_btn.setObjectName("DpIconButton")
        self._lock_btn.setToolTip("Lock (Ctrl+L)")
        self._lock_btn.clicked.connect(self.lock_requested.emit)
        layout.addWidget(self._lock_btn)

        self._logout_btn = QPushButton("⎋", self)
        self._logout_btn.setObjectName("DpIconButton")
        self._logout_btn.setToolTip("Logout")
        self._logout_btn.clicked.connect(self.logout_requested.emit)
        layout.addWidget(self._logout_btn)

        self.refresh_datetime()

    def set_clinic_name(self, name: str) -> None:
        self._clinic_label.setText(name)

    def set_user_display(self, text: str) -> None:
        self._user_btn.setToolTip(f"Account — {text}" if text else "Account")

    def refresh_datetime(self) -> None:
        self._date_label.setText(format_datetime(now()))
