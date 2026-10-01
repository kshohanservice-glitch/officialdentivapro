"""Notifications dropdown for the header bell.

Shows the latest notifications for the current user, marks them read when
the popup opens, and lets the user dismiss or view details.
"""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from dentiva.core.permissions import Principal
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import notification_service


class NotificationsPopup(QFrame):
    """Floating dropdown anchored under the header bell button."""

    dismissed = Signal()

    def __init__(self, session_factory, principal: Principal, parent=None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal
        self.setObjectName("DpNotifPopup")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFixedWidth(360)
        self.setMinimumHeight(200)
        self.setMaximumHeight(500)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Notifications", self)
        title.setObjectName("DpPopupTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._mark_all = QPushButton("Mark all read", self)
        self._mark_all.setFlat(True)
        self._mark_all.clicked.connect(self._mark_all_read)
        header.addWidget(self._mark_all)
        v.addLayout(header)

        self._list = QListWidget(self)
        self._list.setWordWrap(True)
        self._list.setObjectName("DpNotifList")
        v.addWidget(self._list, 1)

        self._unread_badge_value = 0

    # --------------------------------------------------------------- public
    @property
    def unread_count(self) -> int:
        return self._unread_badge_value

    def refresh(self) -> None:
        with UnitOfWork(self._session_factory) as uow:
            self._unread_badge_value = notification_service.unread_count(uow.session, self._principal)
            rows = notification_service.list_notifications(uow.session, self._principal, limit=10)
            uow.commit()
        self._list.clear()
        if not rows:
            it = QListWidgetItem("No notifications yet.", self._list)
            it.setFlags(Qt.NoItemFlags)
            return
        for n in rows:
            title = n["title"]
            message = n.get("message") or ""
            created = n.get("created_at")
            when = _relative_time(created) if isinstance(created, dt.datetime) else ""
            sub_parts = [p for p in (when, message) if p]
            label = title + ("\n" + " · ".join(sub_parts) if sub_parts else "")
            it = QListWidgetItem(label, self._list)
            if n.get("is_read"):
                it.setForeground(Qt.gray)
            else:
                font = it.font()
                font.setBold(True)
                it.setFont(font)

    def open_at(self, pos) -> None:
        self.move(pos)
        self.show()
        self.raise_()
        # Mark visible notifications as read so the badge clears.
        self._mark_all_read()
        self.refresh()

    # -------------------------------------------------------------- private
    def _mark_all_read(self) -> None:
        with UnitOfWork(self._session_factory) as uow:
            notification_service.mark_all_read(uow.session, self._principal)
            uow.commit()
        self._unread_badge_value = 0
        self.refresh()


def _relative_time(d: dt.datetime) -> str:
    from dentiva.core.dates import TZ
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.UTC).astimezone(TZ).replace(tzinfo=None)
    else:
        d = d.astimezone(TZ).replace(tzinfo=None)
    now = dt.datetime.now(TZ).replace(tzinfo=None)
    delta = now - d
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return d.strftime("%d %b %Y")
