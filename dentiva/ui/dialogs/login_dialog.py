"""Login dialog — wired to real authentication via the bootstrap session factory."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from dentiva import __product_name__
from dentiva.core.errors import AuthenticationError, DentivaError
from dentiva.core.permissions import Principal
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import auth_service
from dentiva.ui.design_tokens import Spacing


class LoginDialog(QDialog):
    def __init__(self, session_factory, *, max_attempts: int = 5,
                 lockout_minutes: int = 10, parent=None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._max_attempts = max_attempts
        self._lockout = lockout_minutes
        self.setWindowTitle(f"Sign in — {__product_name__}")
        self.setModal(True)
        self.setMinimumWidth(400)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        self._principal: Optional[Principal] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(Spacing.S6, Spacing.S6, Spacing.S6, Spacing.S6)
        outer.setSpacing(Spacing.S4)

        title = QLabel(__product_name__, self)
        title.setStyleSheet("font-size:22pt; font-weight:700; color:#1F5AA6;")
        subtitle = QLabel("Sign in to continue.", self)
        subtitle.setStyleSheet("color:#475467;")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self._user_edit = QLineEdit(self)
        self._user_edit.setPlaceholderText("Username")
        self._pass_edit = QLineEdit(self)
        self._pass_edit.setPlaceholderText("Password")
        self._pass_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Username:", self._user_edit)
        form.addRow("Password:", self._pass_edit)
        outer.addLayout(form)

        self._error_label = QLabel("", self)
        self._error_label.setStyleSheet("color:#F04438;")
        self._error_label.setWordWrap(True)
        outer.addWidget(self._error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._quit_btn = QPushButton("Quit", self)
        self._quit_btn.clicked.connect(self.reject)
        self._login_btn = QPushButton("Sign in", self)
        self._login_btn.setProperty("variant", "primary")
        self._login_btn.setDefault(True)
        self._login_btn.clicked.connect(self._try_login)
        buttons.addWidget(self._quit_btn)
        buttons.addWidget(self._login_btn)
        outer.addLayout(buttons)

        self._user_edit.setFocus()

    def principal(self) -> Optional[Principal]:
        return self._principal

    def show_error(self, message: str) -> None:
        self._error_label.setText(message)

    def _try_login(self) -> None:
        username = self._user_edit.text()
        password = self._pass_edit.text()
        try:
            with UnitOfWork(self._session_factory) as uow:
                principal = auth_service.authenticate(
                    uow.session, username, password,
                    max_attempts=self._max_attempts,
                    lockout_minutes=self._lockout,
                )
                uow.commit()
            self._principal = principal
            self.accept()
        except AuthenticationError as e:
            self.show_error(e.user_message)
            self._pass_edit.selectAll()
            self._pass_edit.setFocus()
        except DentivaError as e:
            self.show_error(e.user_message)
