"""Placeholder page used for routes that have not yet been built in a phase.

During Phase 2 every nav route is wired to a real placeholder view so there
are no dead tabs/buttons. Subsequent phases replace these with real modules.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from dentiva.ui.design_tokens import Spacing


class PlaceholderView(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.S10, Spacing.S10, Spacing.S10, Spacing.S10)
        layout.setSpacing(Spacing.S2)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        title_lbl = QLabel(title, self)
        title_lbl.setObjectName("DpPageTitle")
        sub = QLabel(subtitle or f"The {title} module will be available in a future phase.", self)
        sub.setObjectName("DpPageSubtitle")
        sub.setWordWrap(True)

        layout.addWidget(title_lbl)
        layout.addWidget(sub)
        layout.addStretch(1)
