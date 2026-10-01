"""Global search popover (Ctrl+K / Ctrl+F).

Floating overlay shown over the main window. Queries
``dashboard_service.global_search`` on every keystroke (debounced) and
displays grouped results. Selecting a result asks the main window to
navigate to the target route.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from dentiva.core.permissions import Principal
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services.dashboard_service import SearchResult, global_search

KIND_LABEL = {
    "patients": "Patients",
    "appointments": "Appointments",
    "invoices": "Invoices",
    "prescriptions": "Prescriptions",
    "inventory": "Inventory",
    "treatments": "Treatments",
    "attachments": "Attachments",
}

# Routes that require selecting an entity inside a page (e.g. open patient
# profile and jump to that id).
_ROUTE_FOR_KIND = None  # filled lazily from dashboard_service if present


class GlobalSearchPopup(QFrame):
    """Modal floating search overlay."""

    result_selected = Signal(str, int)  # route, entity_id
    dismissed = Signal()

    def __init__(self, session_factory, principal: Principal, parent=None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal
        self.setObjectName("DpSearchPopup")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFixedWidth(640)
        self.setMinimumHeight(380)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        bar = QHBoxLayout()
        self._input = QLineEdit(self)
        self._input.setPlaceholderText("Search patients, appointments, invoices… (Esc to close)")
        self._input.setObjectName("DpSearchInput")
        self._input.textChanged.connect(self._on_text_changed)
        bar.addWidget(self._input, 1)
        self._hint = QLabel("Ctrl+K / Ctrl+F", self)
        self._hint.setObjectName("DpSearchHint")
        bar.addWidget(self._hint)
        v.addLayout(bar)

        self._list = QListWidget(self)
        self._list.setObjectName("DpSearchResults")
        self._list.itemActivated.connect(self._on_activated)
        v.addWidget(self._list, 1)

        self._results: list[SearchResult] = []
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self._run_search)

        self._esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._esc.activated.connect(self.dismissed.emit)

        # Parent shortcuts for Ctrl+K and Ctrl+F
        self._shortcut_k = QShortcut(QKeySequence("Ctrl+K"), self)
        self._shortcut_k.setContext(Qt.ApplicationShortcut)
        self._shortcut_k.activated.connect(self.open)
        self._shortcut_f = QShortcut(QKeySequence("Ctrl+F"), self)
        self._shortcut_f.setContext(Qt.ApplicationShortcut)
        self._shortcut_f.activated.connect(self.open)

    # --------------------------------------------------------------- public
    def open(self) -> None:
        if not self.isVisible():
            self.show()
        self.raise_()
        self._input.clear()
        self._input.setFocus()
        self._list.clear()
        self._results = []

    def position_under(self, widget) -> None:
        """Place popup aligned to a widget's bottom-left."""
        if widget is None:
            return
        pos = widget.mapTo(self.parentWidget(), widget.rect().bottomLeft())
        self.move(pos.x() + 8, pos.y() + 6)

    # -------------------------------------------------------------- private
    def _on_text_changed(self, _text: str) -> None:
        self._debounce.start()

    def _run_search(self) -> None:
        q = self._input.text()
        with UnitOfWork(self._session_factory) as uow:
            results = global_search(uow.session, self._principal, q, limit=30)
            uow.commit()
        self._results = results
        self._list.clear()
        if not q.strip():
            return
        if not results:
            it = QListWidgetItem("No matches found", self._list)
            it.setFlags(Qt.NoItemFlags)
            return
        # Group by kind
        current_kind = None
        for r in results:
            if r.kind != current_kind:
                current_kind = r.kind
                header = QListWidgetItem(KIND_LABEL.get(r.kind, r.kind.title()), self._list)
                header.setFlags(Qt.NoItemFlags)
                header.setData(Qt.UserRole, -1)
                font = header.font()
                font.setBold(True)
                header.setFont(font)
            it = QListWidgetItem(f"  {r.title}\n    {r.subtitle}", self._list)
            it.setData(Qt.UserRole, r.entity_id)
            it.setData(Qt.UserRole + 1, r.route)
        if self._list.count():
            self._list.setCurrentRow(1 if self._list.item(0).data(Qt.UserRole) == -1 else 0)

    def _on_activated(self, item: QListWidgetItem) -> None:
        eid = item.data(Qt.UserRole)
        route = item.data(Qt.UserRole + 1)
        if not isinstance(eid, int) or eid < 0 or not route:
            return
        self.result_selected.emit(str(route), int(eid))
        self.hide()
