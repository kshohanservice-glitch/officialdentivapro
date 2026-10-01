# mypy: disable-error-code="arg-type, attr-defined, union-attr"
"""Audit log viewer — filterable, searchable table of all audit events."""
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from dentiva.core.errors import DentivaError
from dentiva.core.permissions import Permission
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.models import User
from dentiva.services import audit_service
from dentiva.ui.design_tokens import Spacing
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from dentiva.core.permissions import Principal


class AuditView(QWidget):
    def __init__(self, session_factory, principal: Principal, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.S4)
        title = QLabel("Audit log", self)
        title.setObjectName("DpPageTitle")
        sub = QLabel(
            "Every significant action is recorded here for compliance and troubleshooting.",
            self,
        )
        sub.setObjectName("DpPageSubtitle")
        root.addWidget(title)
        root.addWidget(sub)

        bar = QHBoxLayout()
        bar.setSpacing(Spacing.S2)
        today = dt.date.today()
        self._start = QDateEdit(self)
        self._start.setCalendarPopup(True)
        self._start.setDisplayFormat("dd MMM yyyy")
        self._start.setDate(today - dt.timedelta(days=30))
        self._end = QDateEdit(self)
        self._end.setCalendarPopup(True)
        self._end.setDisplayFormat("dd MMM yyyy")
        self._end.setDate(today)
        self._action = QComboBox(self)
        self._entity = QComboBox(self)
        self._user = QComboBox(self)
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Search summary…")
        go = QPushButton("Apply", self)
        go.clicked.connect(self._reload)
        bar.addWidget(QLabel("From", self))
        bar.addWidget(self._start)
        bar.addWidget(QLabel("to", self))
        bar.addWidget(self._end)
        bar.addWidget(QLabel("Action", self))
        bar.addWidget(self._action)
        bar.addWidget(QLabel("Entity", self))
        bar.addWidget(self._entity)
        bar.addWidget(QLabel("User", self))
        bar.addWidget(self._user)
        bar.addWidget(self._search, 1)
        bar.addWidget(go)
        root.addLayout(bar)

        self._tbl = QTableWidget(0, 5, self)
        self._tbl.setObjectName("DpDataTable")
        self._tbl.setHorizontalHeaderLabels(["When", "User", "Action", "Entity", "Summary"])
        self._tbl.setEditTriggers(self._tbl.EditTrigger(0))
        self._tbl.verticalHeader().setVisible(False)
        hh = self._tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        root.addWidget(self._tbl, 1)
        self._populate_filters()
        self._reload()

    def refresh(self) -> None:
        self._populate_filters()
        self._reload()

    def _populate_filters(self) -> None:
        try:
            with UnitOfWork(self._sf) as uow:
                actions = audit_service.list_actions(uow.session, self._p)
                entities = audit_service.list_entity_types(uow.session, self._p)
                from sqlalchemy import select
                users = list(uow.session.scalars(select(User).order_by(User.display_name)))
        except DentivaError:
            return
        cur_a = self._action.currentData()
        cur_e = self._entity.currentData()
        cur_u = self._user.currentData()
        self._action.clear()
        self._action.addItem("(all actions)", None)
        for a in actions:
            self._action.addItem(a, a)
        self._entity.clear()
        self._entity.addItem("(all entities)", None)
        for ent in entities:
            self._entity.addItem(ent, ent)
        self._user.clear()
        self._user.addItem("(all users)", None)
        for u in users:
            self._user.addItem(u.display_name or u.username, u.id)
        idx = self._action.findData(cur_a)
        if idx >= 0:
            self._action.setCurrentIndex(idx)
        idx = self._entity.findData(cur_e)
        if idx >= 0:
            self._entity.setCurrentIndex(idx)
        idx = self._user.findData(cur_u)
        if idx >= 0:
            self._user.setCurrentIndex(idx)

    def _reload(self) -> None:
        if not self._p.has(Permission.AUDIT_LOG_VIEW):
            return
        qs = self._start.date()
        qe = self._end.date()
        start = dt.datetime.combine(dt.date(qs.year(), qs.month(), qs.day()), dt.time.min)
        end = dt.datetime.combine(dt.date(qe.year(), qe.month(), qe.day()), dt.time.max)
        try:
            with UnitOfWork(self._sf) as uow:
                from sqlalchemy import select
                users_map = {u.id: (u.display_name or u.username) for u in uow.session.scalars(select(User))}
                events = audit_service.list_events(
                    uow.session, self._p, limit=500,
                    action=self._action.currentData(),
                    entity_type=self._entity.currentData(),
                    user_id=self._user.currentData(),
                    start=start, end=end,
                    search=self._search.text().strip() or None,
                )
        except DentivaError:
            return
        self._tbl.setRowCount(0)
        for ev in events:
            r = self._tbl.rowCount()
            self._tbl.insertRow(r)
            self._tbl.setItem(r, 0, QTableWidgetItem(ev.timestamp.strftime("%d %b %Y %H:%M:%S")))
            self._tbl.setItem(r, 1, QTableWidgetItem(users_map.get(ev.user_id, "—") if ev.user_id else "system"))
            self._tbl.setItem(r, 2, QTableWidgetItem(ev.action))
            ent = ev.entity_type + (f" #{ev.entity_id}" if ev.entity_id else "")
            self._tbl.setItem(r, 3, QTableWidgetItem(ent))
            self._tbl.setItem(r, 4, QTableWidgetItem(ev.summary or ""))
