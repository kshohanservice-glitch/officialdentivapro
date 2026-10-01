"""Activation dialog — now wired to the real activation verifier."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from dentiva import __product_name__
from dentiva.activation import verifier
from dentiva.core.errors import ActivationError
from dentiva.ui.design_tokens import Spacing


class ActivationDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Activate {__product_name__}")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(Spacing.S6, Spacing.S6, Spacing.S6, Spacing.S6)
        outer.setSpacing(Spacing.S4)

        title = QLabel(__product_name__, self)
        title.setStyleSheet("font-size:22pt; font-weight:700; color:#1F5AA6;")
        intro = QLabel(
            "Thank you for installing Dentiva Pro.\n"
            "Please enter the activation code provided with your license to activate the product.\n"
            "Dentiva Pro works fully offline — no account or internet connection is needed.",
            self,
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#475467;")
        outer.addWidget(title)
        outer.addWidget(intro)

        self._code_edit = QLineEdit(self)
        self._code_edit.setPlaceholderText("Activation code")
        self._code_edit.setClearButtonEnabled(True)
        self._code_edit.setMinimumHeight(32)
        outer.addWidget(self._code_edit)

        self._error_label = QLabel("", self)
        self._error_label.setStyleSheet("color:#F04438;")
        self._error_label.setWordWrap(True)
        outer.addWidget(self._error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._quit_btn = QPushButton("Quit", self)
        self._quit_btn.clicked.connect(self.reject)
        self._activate_btn = QPushButton("Activate", self)
        self._activate_btn.setProperty("variant", "primary")
        self._activate_btn.setDefault(True)
        self._activate_btn.clicked.connect(self._try_accept)
        buttons.addWidget(self._quit_btn)
        buttons.addWidget(self._activate_btn)
        outer.addLayout(buttons)

    def _try_accept(self) -> None:
        code = self._code_edit.text().strip()
        if not code:
            self._error_label.setText("Please enter your activation code.")
            self._code_edit.setFocus()
            return
        try:
            verifier.activate(code)
        except ActivationError as e:
            self._error_label.setText(e.user_message)
            self._code_edit.selectAll()
            self._code_edit.setFocus()
            return
        self._error_label.setText("")
        self.accept()
