# mypy: disable-error-code="arg-type, attr-defined, union-attr"
"""Reusable attachment panel for embedding inside patient/visit/prescription/
invoice detail pages.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dentiva.core.errors import PermissionDeniedError, ValidationError
from dentiva.core.permissions import Permission
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import attachment_service
from dentiva.services.attachment_service import format_size


class AttachmentPanel(QWidget):
    """Shows attachments for a single (attachable_type, attachable_id)."""

    def __init__(
        self,
        session_factory,
        principal,
        attachable_type: str,
        attachable_id_getter,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        self._attachable_type = attachable_type
        self._get_id = attachable_id_getter
        self._can_manage = principal.has(Permission.ATTACHMENTS_MANAGE) or principal.is_superuser
        self._build()

    def refresh(self) -> None:
        self._reload()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        intro = QLabel("X-rays, photos, consent forms, and other documents attached to this record.", self)
        intro.setWordWrap(True)
        v.addWidget(intro)

        bar = QHBoxLayout()
        self._upload = QPushButton("Add file…", self)
        self._upload.setProperty("variant", "primary")
        self._upload.clicked.connect(self._on_upload)
        self._upload.setEnabled(self._can_manage)
        self._refresh_btn = QPushButton("Refresh", self)
        self._refresh_btn.clicked.connect(self._reload)
        bar.addWidget(self._upload)
        bar.addWidget(self._refresh_btn)
        bar.addStretch(1)
        v.addLayout(bar)

        self._tbl = QTableWidget(0, 5, self)
        self._tbl.setObjectName("DpDataTable")
        self._tbl.setHorizontalHeaderLabels(["When", "Title", "File", "Size", "Notes"])
        self._tbl.setEditTriggers(self._tbl.EditTrigger(0))
        self._tbl.setSelectionBehavior(self._tbl.SelectionBehavior.SelectRows)
        self._tbl.verticalHeader().setVisible(False)
        hh = self._tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        self._tbl.doubleClicked.connect(self._on_open)
        v.addWidget(self._tbl, 1)

        btn_row = QHBoxLayout()
        self._open_btn = QPushButton("Open", self)
        self._open_btn.clicked.connect(self._on_open)
        self._save_as_btn = QPushButton("Save as…", self)
        self._save_as_btn.clicked.connect(self._on_save_as)
        self._rename_btn = QPushButton("Rename…", self)
        self._rename_btn.clicked.connect(self._on_rename)
        self._rename_btn.setEnabled(self._can_manage)
        self._delete_btn = QPushButton("Remove", self)
        self._delete_btn.setProperty("variant", "danger")
        self._delete_btn.clicked.connect(self._on_delete)
        self._delete_btn.setEnabled(self._can_manage)
        btn_row.addWidget(self._open_btn)
        btn_row.addWidget(self._save_as_btn)
        btn_row.addWidget(self._rename_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._delete_btn)
        v.addLayout(btn_row)
        self._reload()

    # ------------------------------------------------------------ helpers
    def _current_id(self) -> int | None:
        r = self._tbl.currentRow()
        if r < 0:
            return None
        it = self._tbl.item(r, 0)
        return int(it.data(Qt.UserRole)) if it is not None and isinstance(it.data(Qt.UserRole), int) else None

    def _reload(self) -> None:
        aid = self._get_id()
        self._tbl.setRowCount(0)
        if not aid:
            return
        with UnitOfWork(self._sf) as uow:
            rows = attachment_service.list_attachments(
                uow.session, self._p,
                attachable_type=self._attachable_type, attachable_id=aid,
                limit=500,
            )
            uow.commit()
        for a in rows:
            r = self._tbl.rowCount()
            self._tbl.insertRow(r)
            created = a.get("created_at")
            when = created.strftime("%d %b %Y %H:%M") if created else ""
            it = QTableWidgetItem(when)
            it.setData(Qt.UserRole, a["id"])
            self._tbl.setItem(r, 0, it)
            self._tbl.setItem(r, 1, QTableWidgetItem(a.get("title") or a.get("original_filename") or ""))
            self._tbl.setItem(r, 2, QTableWidgetItem(a.get("original_filename") or ""))
            self._tbl.setItem(r, 3, QTableWidgetItem(format_size(int(a.get("size_bytes", 0)))))
            self._tbl.setItem(r, 4, QTableWidgetItem(a.get("notes") or ""))

    # ------------------------------------------------------------ actions
    def _on_upload(self) -> None:
        aid = self._get_id()
        if not aid:
            return
        fn, _ = QFileDialog.getOpenFileName(self, "Attach file", "", "All files (*.*)")
        if not fn:
            return
        try:
            with UnitOfWork(self._sf) as uow:
                attachment_service.upload_attachment_from_path(
                    uow.session, self._p,
                    attachable_type=self._attachable_type, attachable_id=aid,
                    source_path=Path(fn), title=Path(fn).name, notes="",
                )
                uow.commit()
        except (PermissionDeniedError, ValidationError, ValueError) as e:
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
        dst, _ = QFileDialog.getSaveFileName(self, "Save as", suggested)
        if not dst:
            return
        shutil.copyfile(handle.full_path, dst)

    def _on_rename(self) -> None:
        aid = self._current_id()
        if aid is None:
            return
        with UnitOfWork(self._sf) as uow:
            rows = attachment_service.list_attachments(
                uow.session, self._p,
                attachable_type=self._attachable_type, attachable_id=self._get_id(),
                limit=500,
            )
            uow.commit()
        target = next((r for r in rows if r["id"] == aid), None)
        if not target:
            return
        title, ok = QInputDialog.getText(self, "Rename attachment", "Title:", text=target["title"])
        if not ok:
            return
        notes, ok = QInputDialog.getText(self, "Attachment notes", "Notes:", text=target.get("notes") or "")
        if not ok:
            notes = target.get("notes") or ""
        with UnitOfWork(self._sf) as uow:
            attachment_service.update_attachment(uow.session, self._p, aid, title=title, notes=notes)
            uow.commit()
        self._reload()

    def _on_delete(self) -> None:
        aid = self._current_id()
        if aid is None:
            return
        reply = QMessageBox.question(
            self, "Remove attachment",
            "Remove this attachment permanently?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
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
        except Exception:  # pragma: no cover
            QMessageBox.information(self, "File", str(path))
