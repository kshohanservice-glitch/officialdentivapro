"""Lock dialog: shown when auto-lock engages or the user clicks Lock."""
from __future__ import annotations

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
from dentiva.ui.design_tokens import Spacing


class LockDialog(QDialog):
    def __init__(self, username: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Locked — {__product_name__}")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(Spacing.S6, Spacing.S6, Spacing.S6, Spacing.S6)
        outer.setSpacing(Spacing.S4)

        title = QLabel(__product_name__, self)
        title.setStyleSheet("font-size:18pt; font-weight:700; color:#1F5AA6;")
        who = QLabel(f"Session locked for <b>{username}</b>. Enter your password to continue.", self)
        who.setWordWrap(True)
        who.setStyleSheet("color:#475467;")
        outer.addWidget(title)
        outer.addWidget(who)

        form = QFormLayout()
        self._pass_edit = QLineEdit(self)
        self._pass_edit.setEchoMode(QLineEdit.Password)
        self._pass_edit.setPlaceholderText("Password")
        form.addRow("Password:", self._pass_edit)
        outer.addLayout(form)

        self._error_label = QLabel("", self)
        self._error_label.setStyleSheet("color:#F04438;")
        outer.addWidget(self._error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._logout_btn = QPushButton("Logout", self)
        self._logout_btn.clicked.connect(self._logout)
        self._unlock_btn = QPushButton("Unlock", self)
        self._unlock_btn.setProperty("variant", "primary")
        self._unlock_btn.setDefault(True)
        self._unlock_btn.clicked.connect(self._try_unlock)
        buttons.addWidget(self._logout_btn)
        buttons.addWidget(self._unlock_btn)
        outer.addLayout(buttons)

        self._should_logout = False

    def password(self) -> str:
        return self._pass_edit.text()

    def show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._pass_edit.selectAll()
        self._pass_edit.setFocus()

    def should_logout(self) -> bool:
        return self._should_logout

    def _logout(self) -> None:
        self._should_logout = True
        self.reject()

    def _try_unlock(self) -> None:
        if not self._pass_edit.text():
            self.show_error("Please enter your password.")
            return
        self.accept()
