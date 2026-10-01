# mypy: disable-error-code="arg-type, attr-defined, union-attr"
"""Dedicated Attachments page: browse all attachments, upload new ones,
download, rename, and delete."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dentiva.core.errors import PermissionDeniedError, ValidationError
from dentiva.core.permissions import Permission
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import attachment_service
from dentiva.services.attachment_service import format_size
from dentiva.ui.design_tokens import Spacing
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

KIND_LABEL = {
    "patient": "Patient",
    "visit": "Visit",
    "prescription": "Prescription",
    "invoice": "Invoice",
}


class AttachmentsView(QWidget):
    def __init__(self, session_factory, principal, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        self._can_manage = principal.has(Permission.ATTACHMENTS_MANAGE) or principal.is_superuser
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.S4)

        title = QLabel("Attachments", self)
        title.setObjectName("DpPageTitle")
        sub = QLabel("Files attached to patient records, visits, prescriptions, and invoices. Double-click a row to open.", self)
        sub.setObjectName("DpPageSubtitle")
        sub.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(sub)

        bar = QHBoxLayout()
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Filter by filename, title, or notes…")
        self._search.textChanged.connect(lambda _t: self._reload())
        bar.addWidget(self._search, 1)
        self._upload = QPushButton("Upload file…", self)
        self._upload.setProperty("variant", "primary")
        self._upload.clicked.connect(self._on_upload)
        self._upload.setEnabled(self._can_manage)
        self._refresh = QPushButton("Refresh", self)
        self._refresh.clicked.connect(self._reload)
        bar.addWidget(self._upload)
        bar.addWidget(self._refresh)
        root.addLayout(bar)

        self._tbl = QTableWidget(0, 6, self)
        self._tbl.setObjectName("DpDataTable")
        self._tbl.setHorizontalHeaderLabels(["When", "Type", "Attached to", "Title", "File", "Size"])
        self._tbl.setEditTriggers(self._tbl.EditTrigger(0))
        self._tbl.setSelectionBehavior(self._tbl.SelectionBehavior.SelectRows)
        self._tbl.setSelectionMode(self._tbl.SingleSelection)
        self._tbl.verticalHeader().setVisible(False)
        hh = self._tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self._tbl.doubleClicked.connect(self._on_open)
        self._tbl.setContextMenuPolicy(Qt.ActionsContextMenu)
        root.addWidget(self._tbl, 1)

        btn_row = QHBoxLayout()
        self._open_btn = QPushButton("Open", self)
        self._open_btn.clicked.connect(self._on_open)
        self._rename_btn = QPushButton("Rename title…", self)
        self._rename_btn.clicked.connect(self._on_rename)
        self._rename_btn.setEnabled(self._can_manage)
        self._save_as_btn = QPushButton("Save as…", self)
        self._save_as_btn.clicked.connect(self._on_save_as)
        self._delete_btn = QPushButton("Delete", self)
        self._delete_btn.setProperty("variant", "danger")
        self._delete_btn.clicked.connect(self._on_delete)
        self._delete_btn.setEnabled(self._can_manage)
        btn_row.addWidget(self._open_btn)
        btn_row.addWidget(self._save_as_btn)
        btn_row.addWidget(self._rename_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._delete_btn)
        root.addLayout(btn_row)

        self._reload()

    def refresh(self) -> None:
        self._reload()

    # --------------------------------------------------------------- data
    def _reload(self) -> None:
        flt = self._search.text().strip().lower()
        with UnitOfWork(self._sf) as uow:
            rows = attachment_service.list_attachments(uow.session, self._p, limit=500)
            uow.commit()
        self._tbl.setRowCount(0)
        for a in rows:
            if flt:
                hay = " ".join([
                    (a.get("title") or ""),
                    (a.get("original_filename") or ""),
                    (a.get("notes") or ""),
                    (a.get("attachable_type") or ""),
                ]).lower()
                if flt not in hay:
                    continue
            r = self._tbl.rowCount()
            self._tbl.insertRow(r)
            created = a.get("created_at")
            when = created.strftime("%d %b %Y %H:%M") if created else ""
            self._tbl.setItem(r, 0, QTableWidgetItem(when))
            self._tbl.setItem(r, 1, QTableWidgetItem(KIND_LABEL.get(a["attachable_type"], a["attachable_type"])))
            self._tbl.setItem(r, 2, QTableWidgetItem(f"{a['attachable_type']} #{a['attachable_id']}"))
            self._tbl.setItem(r, 3, QTableWidgetItem(a.get("title") or a.get("original_filename") or ""))
            self._tbl.setItem(r, 4, QTableWidgetItem(a.get("original_filename") or ""))
            self._tbl.setItem(r, 5, QTableWidgetItem(format_size(int(a.get("size_bytes", 0)))))
            self._tbl.item(r, 0).setData(Qt.UserRole, a["id"])

    def _current_id(self) -> int | None:
        r = self._tbl.currentRow()
        if r < 0:
            return None
        it = self._tbl.item(r, 0)
        if it is None:
            return None
        v = it.data(Qt.UserRole)
        return int(v) if isinstance(v, int) else None

    # ----------------------------------------------------------- actions
    def _on_upload(self) -> None:
        # Prompt for a patient (code or partial name) first.
        from dentiva.models import Patient
        from sqlalchemy import or_, select
        text, ok = QInputDialog.getText(
            self, "Upload attachment",
            "Enter the patient code or part of the patient's name to attach this file to:",
        )
        if not ok or not text.strip():
            return
        needle = text.strip()
        try:
            with UnitOfWork(self._sf) as uow:
                patient = uow.session.scalars(
                    select(Patient).where(
                        or_(Patient.patient_code.ilike(needle),
                            Patient.name.ilike(f"%{needle}%")),
                        Patient.deleted_at.is_(None),
                    ).limit(1)
                ).first()
                uow.commit()
        except Exception:
            patient = None
        if patient is None:
            QMessageBox.warning(self, "Patient not found", f"No patient matched '{needle}'.")
            return
        fn, _ = QFileDialog.getOpenFileName(self, "Choose file to attach", "", "All files (*.*)")
        if not fn:
            return
        src = Path(fn)
        try:
            with UnitOfWork(self._sf) as uow:
                attachment_service.upload_attachment_from_path(
                    uow.session, self._p,
                    attachable_type="patient", attachable_id=patient.id,
                    source_path=src, title=src.name, notes="",
                )
                uow.commit()
        except (ValidationError, PermissionDeniedError, ValueError) as e:
            QMessageBox.warning(self, "Upload failed", getattr(e, "user_message", str(e)))
            return
        self._reload()

    def _on_open(self) -> None:
        aid = self._current_id()
        if aid is None:
            return
        try:
            with UnitOfWork(self._sf) as uow:
                handle = attachment_service.open_attachment(uow.session, self._p, aid)
                uow.commit()
        except (FileNotFoundError, PermissionDeniedError) as e:
            QMessageBox.warning(self, "Cannot open", str(e))
            return
        self._open_native(handle.full_path)

    def _on_save_as(self) -> None:
        aid = self._current_id()
        if aid is None:
            return
        try:
            with UnitOfWork(self._sf) as uow:
                handle = attachment_service.open_attachment(uow.session, self._p, aid)
                suggested = handle.attachment.original_filename or "attachment"
                uow.commit()
        except (FileNotFoundError, PermissionDeniedError) as e:
            QMessageBox.warning(self, "Cannot open", str(e))
            return
        dst, _ = QFileDialog.getSaveFileName(self, "Save attachment as", suggested)
        if not dst:
            return
        import shutil as _sh
        _sh.copyfile(handle.full_path, dst)

    def _on_rename(self) -> None:
        aid = self._current_id()
        if aid is None:
            return
        with UnitOfWork(self._sf) as uow:
            rows = attachment_service.list_attachments(uow.session, self._p, limit=1000)
            uow.commit()
        target = next((r for r in rows if r["id"] == aid), None)
        if not target:
            return
        new_title, ok = QInputDialog.getText(
            self, "Rename attachment", "Title:", text=target["title"],
        )
        if not ok:
            return
        with UnitOfWork(self._sf) as uow:
            attachment_service.update_attachment(uow.session, self._p, aid, title=new_title)
            uow.commit()
        self._reload()

    def _on_delete(self) -> None:
        aid = self._current_id()
        if aid is None:
            return
        reply = QMessageBox.question(
            self, "Delete attachment",
            "Delete this attachment permanently? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        with UnitOfWork(self._sf) as uow:
            attachment_service.delete_attachment(uow.session, self._p, aid)
            uow.commit()
        self._reload()

    def _open_native(self, path: Path) -> None:
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:  # pragma: no cover
            QMessageBox.information(self, "File", str(path))
