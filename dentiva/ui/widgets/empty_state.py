"""Empty state widget for lists / modules without data."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from dentiva.ui.design_tokens import Spacing


class EmptyState(QWidget):
    def __init__(
        self,
        title: str,
        message: str,
        action_text: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("DpEmptyState")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.S1)
        layout.setAlignment(Qt.AlignCenter)

        self._title = QLabel(title, self)
        self._title.setObjectName("DpEmptyStateTitle")
        self._title.setAlignment(Qt.AlignCenter)
        self._msg = QLabel(message, self)
        self._msg.setObjectName("DpEmptyStateText")
        self._msg.setWordWrap(True)
        self._msg.setAlignment(Qt.AlignCenter)

        layout.addStretch(1)
        layout.addWidget(self._title, 0, Qt.AlignCenter)
        layout.addWidget(self._msg, 0, Qt.AlignCenter)
        self._button: QPushButton | None = None
        if action_text:
            self._button = QPushButton(action_text, self)
            self._button.setProperty("variant", "primary")
            layout.addWidget(self._button, 0, Qt.AlignCenter)
        layout.addStretch(1)

    def button(self) -> QPushButton | None:
        return self._button
