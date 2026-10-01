"""Patients view: searchable list, create/edit dialog, soft-delete.

The view is RBAC-aware: buttons are shown/hidden based on the current
principal and the service layer double-checks all operations.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from dentiva.core.permissions import Permission, Principal
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.models import Patient
from dentiva.services import patient_service
from dentiva.ui.design_tokens import Spacing
from dentiva.ui.dialogs.patient_dialog import PatientFormDialog, confirm_delete_patient
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
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
    pass


COLUMNS = ("Code", "Name", "Phone", "Gender", "Age", "Blood", "Last visit", "Visits")


class PatientsView(QWidget):
    """Patients list + toolbar."""

    patient_opened = Signal(int)  # emits patient id on open

    def __init__(self, session_factory, principal: Principal, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(Spacing.S4)

        title = QLabel("Patients", self)
        title.setObjectName("DpPageTitle")
        subtitle = QLabel("Manage patient records, medical history, and contact details.", self)
        subtitle.setObjectName("DpPageSubtitle")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        # Toolbar
        bar = QHBoxLayout()
        bar.setSpacing(Spacing.S3)
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Search by name, phone, or code…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_changed)
        bar.addWidget(self._search, 1)

        self._count_label = QLabel("", self)
        self._count_label.setObjectName("DpPageSubtitle")
        bar.addWidget(self._count_label)

        self._new_btn = QPushButton("+ New patient", self)
        self._new_btn.setProperty("variant", "primary")
        self._new_btn.clicked.connect(self._on_new)
        self._new_btn.setVisible(self._principal.has(Permission.PATIENTS_CREATE))
        bar.addWidget(self._new_btn)
        outer.addLayout(bar)

        # Table
        self._table = QTableWidget(self)
        self._table.setObjectName("DpDataTable")
        self._table.setColumnCount(len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setFrameShape(QFrame.StyledPanel)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self._table.doubleClicked.connect(self._on_open_row)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        # We'll add actions inline as a column instead of a context menu for
        # keyboard accessibility.
        outer.addWidget(self._table, 1)

        # Debounce timer for search.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self.refresh)

        self._patients: list[Patient] = []
        self.refresh()

    # ----------------------------------------------------------------- API
    def refresh(self) -> None:
        if not self._principal.has(Permission.PATIENTS_VIEW):
            self._table.setRowCount(0)
            self._count_label.setText("(no permission to view patients)")
            return
        q = self._search.text()
        with UnitOfWork(self._session_factory) as uow:
            patients = patient_service.list_patients(uow.session, self._principal, query=q, limit=1000)
            total = patient_service.count_patients(uow.session, self._principal, query=q)
            uow.commit()
        self._patients = patients
        self._table.setRowCount(len(patients))
        for r, p in enumerate(patients):
            cells = [
                p.patient_code,
                p.name,
                p.phone or "",
                p.gender or "",
                str(p.age_cache) if p.age_cache is not None else "",
                p.blood_group or "",
                _fmt_last_visit(p.last_visit_at),
                str(p.visit_count or 0),
            ]
            for c, val in enumerate(cells):
                it = QTableWidgetItem(val)
                it.setData(Qt.UserRole, p.id)
                if c == 0:
                    it.setTextAlignment(Qt.AlignCenter)
                self._table.setItem(r, c, it)
            # Action buttons
            self._add_action_buttons(r, p)
        shown = len(patients)
        if q:
            self._count_label.setText(f"{shown} of {total} match")
        else:
            self._count_label.setText(f"{total} patient(s) total")

    def select_patient(self, patient_id: int) -> None:
        """Select and open a patient by id (used by global search)."""
        for r in range(self._table.rowCount()):
            item = self._table.item(r, 0)
            if item and item.data(Qt.UserRole) == patient_id:
                self._table.selectRow(r)
                self._on_open_row(self._table.model().index(r, 0))
                return

    # -------------------------------------------------------------- private
    def _add_action_buttons(self, row: int, patient: Patient) -> None:
        # We re-use column 0 to hold the code; add an overlay widget via a
        # dedicated widget column is overkill. Instead add action buttons by
        # setting cell widgets on the right side — but our columns don't have
        # an action column. Use a small inline action layout via setCellWidget
        # in an extra 9th column.
        if self._table.columnCount() == len(COLUMNS):
            self._table.setColumnCount(len(COLUMNS) + 1)
            self._table.setHorizontalHeaderItem(len(COLUMNS), QTableWidgetItem(""))
            self._table.horizontalHeader().setSectionResizeMode(len(COLUMNS), QHeaderView.ResizeToContents)
        cell = QWidget(self._table)
        h = QHBoxLayout(cell)
        h.setContentsMargins(Spacing.S1, Spacing.S1, Spacing.S1, Spacing.S1)
        h.setSpacing(Spacing.S1)
        open_btn = QPushButton("Open", cell)
        open_btn.clicked.connect(lambda _=False, pid=patient.id: self._open_patient(pid))
        h.addWidget(open_btn)
        edit_btn = QPushButton("Edit", cell)
        edit_btn.setEnabled(self._principal.has(Permission.PATIENTS_EDIT))
        edit_btn.clicked.connect(lambda _=False, p=patient: self._on_edit(p))
        h.addWidget(edit_btn)
        del_btn = QPushButton("Delete", cell)
        del_btn.setProperty("variant", "destructive")
        del_btn.setEnabled(self._principal.has(Permission.PATIENTS_DELETE))
        del_btn.clicked.connect(lambda _=False, p=patient: self._on_delete(p))
        h.addWidget(del_btn)
        self._table.setCellWidget(row, len(COLUMNS), cell)

    def _on_search_changed(self, _text: str) -> None:
        self._search_timer.start()

    def _on_new(self) -> None:
        dlg = PatientFormDialog(self._session_factory, self._principal, parent=self)
        if dlg.exec():
            self.refresh()

    def _on_edit(self, patient: Patient) -> None:
        dlg = PatientFormDialog(self._session_factory, self._principal, patient=patient, parent=self)
        if dlg.exec():
            self.refresh()

    def _on_delete(self, patient: Patient) -> None:
        if confirm_delete_patient(self, self._session_factory, self._principal, patient):
            self.refresh()

    def _on_open_row(self, index) -> None:
        row = index.row()
        if row < 0 or row >= len(self._patients):
            return
        pid = self._patients[row].id
        self._open_patient(pid)

    def _open_patient(self, patient_id: int) -> None:
        # Phase 5 doesn't yet ship patient profile; emit signal for future.
        self.patient_opened.emit(patient_id)
        # Use status bar message — main window will route to profile later.
        mw = self.window()
        show_msg = getattr(mw, "show_message", None)
        if callable(show_msg):
            show_msg(f"Patient profile will open in Phase 6 (id={patient_id}).", timeout=3000)


def _fmt_last_visit(ts) -> str:
    if ts is None:
        return "—"
    from dentiva.core.dates import format_datetime
    return format_datetime(ts)
