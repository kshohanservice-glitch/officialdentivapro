# mypy: disable-error-code="arg-type, attr-defined, union-attr"
"""Dedicated Notifications view (bell popup shows last 10
this shows the full list)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from dentiva.core.errors import DentivaError
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import notification_service
from dentiva.ui.design_tokens import Spacing
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    pass


KIND_LABELS = {
    "appt_upcoming": "Upcoming appointment",
    "day_summary": "Daily summary",
    "low_stock": "Low stock",
    "overdue_invoice": "Overdue invoice",
}


class NotificationsView(QWidget):
    def __init__(self, session_factory, principal, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.S4)

        title = QLabel("Notifications", self)
        title.setObjectName("DpPageTitle")
        sub = QLabel("All in-app alerts. Mark items read and review at your convenience.", self)
        sub.setObjectName("DpPageSubtitle")
        root.addWidget(title)
        root.addWidget(sub)

        bar = QHBoxLayout()
        self._filter = QComboBox(self)
        self._filter.addItem("All", None)
        self._filter.addItem("Unread only", "unread")
        for k, lbl in KIND_LABELS.items():
            self._filter.addItem(lbl, k)
        self._filter.currentIndexChanged.connect(lambda _i: self._reload())
        self._mark_all = QPushButton("Mark all read", self)
        self._mark_all.clicked.connect(self._on_mark_all)
        refresh = QPushButton("Refresh", self)
        refresh.clicked.connect(self._reload)
        bar.addWidget(QLabel("Filter:", self))
        bar.addWidget(self._filter)
        bar.addStretch(1)
        bar.addWidget(self._mark_all)
        bar.addWidget(refresh)
        root.addLayout(bar)

        self._tbl = QTableWidget(0, 5, self)
        self._tbl.setObjectName("DpDataTable")
        self._tbl.setHorizontalHeaderLabels(["When", "Type", "Title", "Message", "Status"])
        self._tbl.setEditTriggers(self._tbl.EditTrigger(0))
        self._tbl.setSelectionBehavior(self._tbl.SelectionBehavior.SelectRows)
        self._tbl.verticalHeader().setVisible(False)
        hh = self._tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        root.addWidget(self._tbl, 1)
        self._reload()

    def refresh(self) -> None:
        self._reload()

    def _reload(self) -> None:
        f = self._filter.currentData()
        try:
            with UnitOfWork(self._sf) as uow:
                if f == "unread":
                    rows = notification_service.list_notifications(
                        uow.session, self._p, status_filter="unread", limit=500,
                    )
                elif f is None:
                    rows = notification_service.list_notifications(uow.session, self._p, limit=500)
                else:
                    rows = notification_service.list_notifications(
                        uow.session, self._p, kind_filter=f, limit=500,
                    )
                uow.commit()
        except DentivaError:
            return
        self._tbl.setRowCount(0)
        for n in rows:
            r = self._tbl.rowCount()
            self._tbl.insertRow(r)
            created = n.get("created_at")
            when = created.strftime("%d %b %Y %H:%M") if created else ""
            self._tbl.setItem(r, 0, QTableWidgetItem(when))
            kind = n.get("kind", "")
            self._tbl.setItem(r, 1, QTableWidgetItem(KIND_LABELS.get(kind, kind)))
            self._tbl.setItem(r, 2, QTableWidgetItem(n.get("title", "")))
            self._tbl.setItem(r, 3, QTableWidgetItem(n.get("message", "")))
            is_read = bool(n.get("is_read"))
            status = QTableWidgetItem("Read" if is_read else "New")
            if not is_read:
                fnt = status.font()
                fnt.setBold(True)
                status.setFont(fnt)
            self._tbl.setItem(r, 4, status)

    def _on_mark_all(self) -> None:
        try:
            with UnitOfWork(self._sf) as uow:
                notification_service.mark_all_read(uow.session, self._p)
                uow.commit()
        except DentivaError:
            return
        self._reload()
