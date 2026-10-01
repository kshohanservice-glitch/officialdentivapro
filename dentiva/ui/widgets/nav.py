"""Sidebar navigation widget."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dentiva.ui.design_tokens import Shell, Spacing


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon_char: str = ""
    permission: str | None = None  # optional permission key for future RBAC filtering


@dataclass(frozen=True)
class NavSection:
    title: str
    items: tuple[NavItem, ...]


# Default navigation matching the product specification.
DEFAULT_NAV: tuple[NavSection, ...] = (
    NavSection(
        "Practice",
        (
            NavItem("dashboard", "Dashboard", "▣"),
            NavItem("patients", "Patients", "♚"),
            NavItem("appointments", "Appointments", "▤"),
            NavItem("queue", "Queue", "≡"),
        ),
    ),
    NavSection(
        "Clinical",
        (
            NavItem("treatments", "Treatments", "✚"),
            NavItem("prescriptions", "Prescriptions", "℞"),
        ),
    ),
    NavSection(
        "Billing",
        (
            NavItem("invoices", "Invoice", "▢"),
            NavItem("payments", "Payments", "৳"),
            NavItem("inventory", "Inventory", "▣"),
            NavItem("accounting", "Accounting", "∑"),
        ),
    ),
    NavSection(
        "Administration",
        (
            NavItem("staff", "Staff & Users", "☺"),
            NavItem("backup", "Backup & Restore", "⎘"),
            NavItem("settings", "Settings", "⚙"),
            NavItem("about", "About", "ⓘ"),
        ),
    ),
)


class NavButton(QPushButton):
    """Sidebar navigation button."""

    def __init__(self, item: NavItem, collapsed: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self.setObjectName("DpNavButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.set_collapsed(collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed:
            self.setText(self.item.icon_char or self.item.label[0])
            self.setToolTip(self.item.label)
            self.setProperty("collapsed", True)
            self.setFixedHeight(40)
        else:
            text = f"{self.item.icon_char}  {self.item.label}" if self.item.icon_char else self.item.label
            self.setText(text)
            self.setToolTip("")
            self.setProperty("collapsed", False)
            self.setFixedHeight(36)
        self.style().unpolish(self)
        self.style().polish(self)


class Sidebar(QFrame):
    """Collapsible left navigation sidebar."""

    nav_selected = Signal(str)
    toggle_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DpSidebar")
        self._collapsed = False
        self._buttons: dict[str, NavButton] = {}
        self._current_key: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, Spacing.S2, 0, Spacing.S2)
        outer.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("DpSidebarScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._inner = QWidget(self._scroll)
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(0, 0, 0, 0)
        self._inner_layout.setSpacing(0)

        self._build_nav()

        self._inner_layout.addStretch(1)
        self._scroll.setWidget(self._inner)
        outer.addWidget(self._scroll, 1)

        self.setFixedWidth(Shell.SIDEBAR_EXPANDED)

    def _build_nav(self) -> None:
        for section in DEFAULT_NAV:
            label = QLabel(section.title, self._inner)
            label.setObjectName("DpNavSectionLabel")
            self._inner_layout.addWidget(label)
            for item in section.items:
                btn = NavButton(item, collapsed=False, parent=self._inner)
                btn.clicked.connect(lambda _checked=False, k=item.key: self._select(k))
                self._buttons[item.key] = btn
                self._inner_layout.addWidget(btn)

    def _select(self, key: str) -> None:
        self.set_current(key)
        self.nav_selected.emit(key)

    def set_current(self, key: str) -> None:
        self._current_key = key
        for k, btn in self._buttons.items():
            btn.setChecked(k == key)
            btn.setProperty("active", k == key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def current_key(self) -> str | None:
        return self._current_key

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self.setFixedWidth(Shell.SIDEBAR_COLLAPSED if collapsed else Shell.SIDEBAR_EXPANDED)
        for btn in self._buttons.values():
            btn.set_collapsed(collapsed)
        # Hide section labels when collapsed.
        for child in self._inner.findChildren(QLabel):
            if child.objectName() == "DpNavSectionLabel":
                child.setVisible(not collapsed)
