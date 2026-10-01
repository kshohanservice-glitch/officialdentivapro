"""Card widgets."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from dentiva.ui.design_tokens import Spacing


class Card(QFrame):
    """A simple bordered card container."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DpCard")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(Spacing.S5, Spacing.S5, Spacing.S5, Spacing.S5)
        self._layout.setSpacing(Spacing.S2)

    def set_title(self, title: str) -> None:
        label = QLabel(title, self)
        label.setObjectName("DpCardTitle")
        self._layout.insertWidget(0, label)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def set_body_layout(self, layout) -> None:
        """Replace body with a caller-supplied layout (after title)."""
        self._layout.addLayout(layout)


class StatTile(QFrame):
    """Dashboard stat tile."""

    def __init__(self, label: str, value: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DpStatTile")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.S5, Spacing.S5, Spacing.S5, Spacing.S5)
        layout.setSpacing(Spacing.S1)
        self._value_label = QLabel(value, self)
        self._value_label.setObjectName("DpStatValue")
        self._label_label = QLabel(label, self)
        self._label_label.setObjectName("DpStatLabel")
        layout.addWidget(self._value_label, 0, Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self._label_label, 0, Qt.AlignLeft)
        layout.addStretch(1)

    def set_value(self, value: str) -> None:
        self._value_label.setText(value)

    def set_label(self, label: str) -> None:
        self._label_label.setText(label)
