"""Dashboard view — operational tiles, upcoming appointments, alerts.

All data is fetched via :mod:`dentiva.services.dashboard_service` which
gracefully hides tiles for entities the principal cannot view. Tiles refresh
every 60 seconds and whenever the view becomes visible (via ``refresh()``).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from dentiva.core.dates import format_date, today
from dentiva.core.permissions import Permission, Principal
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services.dashboard_service import DashboardData, load_dashboard
from dentiva.ui.design_tokens import Spacing
from dentiva.ui.widgets.cards import Card, StatTile
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    pass


STATUS_STYLES = {
    "scheduled": "color:#475467;",
    "confirmed": "color:#027A48;",
    "checked_in": "color:#B54708;",
    "in_progress": "color:#6941C6;",
    "completed": "color:#475467;",
    "waiting": "color:#B54708;",
    "with_dentist": "color:#6941C6;",
    "cancelled": "color:#B42318; text-decoration: line-through;",
}


class DashboardView(QWidget):
    def __init__(self, session_factory, principal: Principal, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(Spacing.S5)

        # Title
        self._title = QLabel("Dashboard", self)
        self._title.setObjectName("DpPageTitle")
        self._subtitle = QLabel("", self)
        self._subtitle.setObjectName("DpPageSubtitle")
        self._subtitle.setWordWrap(True)
        outer.addWidget(self._title)
        outer.addWidget(self._subtitle)

        # Stat tiles
        self._tiles: dict[str, StatTile] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(Spacing.S4)
        grid.setVerticalSpacing(Spacing.S4)
        tile_specs = [
            ("appts", "Today's appointments", "—"),
            ("checkins", "Checked in", "—"),
            ("queue", "Waiting in queue", "—"),
            ("revenue", "Today's revenue", "৳0.00"),
            ("pending_inv", "Pending invoices", "—"),
            ("low_stock", "Low stock alerts", "—"),
        ]
        for idx, (key, label, value) in enumerate(tile_specs):
            tile = StatTile(label, value, self)
            self._tiles[key] = tile
            grid.addWidget(tile, idx // 3, idx % 3)
        outer.addLayout(grid)

        # Lower section: upcoming appointments + alerts
        lower = QHBoxLayout()
        lower.setSpacing(Spacing.S4)

        self._upcoming_card = Card(self)
        self._upcoming_card.set_title("Upcoming appointments")
        self._upcoming_list = QListWidget(self._upcoming_card)
        self._upcoming_list.setObjectName("DpUpcomingList")
        self._upcoming_list.setMinimumHeight(180)
        self._upcoming_card.add_widget(self._upcoming_list)
        lower.addWidget(self._upcoming_card, 2)

        self._alerts_card = Card(self)
        self._alerts_card.set_title("Alerts")
        self._alerts_list = QListWidget(self._alerts_card)
        self._alerts_list.setObjectName("DpAlertsList")
        self._alerts_list.setMinimumHeight(180)
        self._alerts_card.add_widget(self._alerts_list)
        lower.addWidget(self._alerts_card, 1)
        outer.addLayout(lower)
        outer.addStretch(1)

        # Refresh timer (every 60 seconds) and immediate first load.
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

        self.refresh()

    # ------------------------------------------------------------------ API
    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        # Refresh whenever the view becomes visible so data is fresh.
        QTimer.singleShot(0, self.refresh)

    def refresh(self) -> None:
        with UnitOfWork(self._session_factory) as uow:
            data: DashboardData = load_dashboard(uow.session, self._principal)
            uow.commit()
        self._apply(data)

    # -------------------------------------------------------------- private
    def _apply(self, d: DashboardData) -> None:
        date_str = format_date(today())
        if d.clinic_name:
            self._title.setText(f"Dashboard — {d.clinic_name}")
        self._subtitle.setText(f"{date_str} · Welcome back, {self._principal.display_name}.")

        self._tiles["appts"].set_value(str(d.today_appointments))
        self._tiles["checkins"].set_value(str(d.checked_in))
        self._tiles["queue"].set_value(str(d.waiting_queue))
        self._tiles["revenue"].set_value(d.todays_revenue_display)
        self._tiles["pending_inv"].set_value(str(d.pending_invoices_count))
        self._tiles["low_stock"].set_value(str(d.low_stock_count))

        # Hide tiles the principal cannot see (they'd always be zero / "—").
        self._tiles["appts"].setVisible(self._principal.has(Permission.APPOINTMENTS_VIEW))
        self._tiles["checkins"].setVisible(self._principal.has(Permission.APPOINTMENTS_VIEW))
        self._tiles["queue"].setVisible(self._principal.has(Permission.QUEUE_MANAGE))
        revenue_visible = (
            self._principal.has(Permission.PAYMENTS_VIEW)
            or self._principal.has(Permission.INVOICES_VIEW)
            or self._principal.has(Permission.ACCOUNTING_VIEW)
            or self._principal.has(Permission.FINANCIAL_REPORTS_VIEW)
        )
        self._tiles["revenue"].setVisible(revenue_visible)
        self._tiles["pending_inv"].setVisible(self._principal.has(Permission.INVOICES_VIEW))
        self._tiles["low_stock"].setVisible(self._principal.has(Permission.INVENTORY_VIEW))

        self._upcoming_list.clear()
        if not d.upcoming:
            it = QListWidgetItem("No upcoming appointments today.", self._upcoming_list)
            it.setFlags(Qt.NoItemFlags)
        else:
            for row in d.upcoming:
                label_parts = [f"{row.time_str}  —  {row.patient_name}"]
                if row.dentist_name and row.dentist_name != "—":
                    label_parts.append(f"Dentist: {row.dentist_name}")
                if row.reason:
                    label_parts.append(row.reason)
                text = "\n".join(label_parts)
                item = QListWidgetItem(text, self._upcoming_list)
                item.setData(Qt.UserRole, row.status)
                item.setToolTip(row.patient_phone or "")
                style = STATUS_STYLES.get(row.status, "")
                if style:
                    # Apply status color via a small widget wrapper? We can't
                    # style individual items with stylesheets easily, but we
                    # can set foreground.
                    color = _status_color(row.status)
                    if color.isValid():
                        item.setForeground(color)

        self._alerts_list.clear()
        if not d.alerts:
            it = QListWidgetItem("All caught up — no alerts.", self._alerts_list)
            it.setFlags(Qt.NoItemFlags)
        else:
            for a in d.alerts:
                text = f"{a.title}\n{a.detail}"
                it = QListWidgetItem(text, self._alerts_list)
                it.setToolTip(a.kind)


def _status_color(status: str):
    from PySide6.QtGui import QColor
    mapping = {
        "confirmed": QColor("#027A48"),
        "checked_in": QColor("#B54708"),
        "in_progress": QColor("#6941C6"),
        "waiting": QColor("#B54708"),
        "with_dentist": QColor("#6941C6"),
        "cancelled": QColor("#B42318"),
    }
    return mapping.get(status, QColor())
