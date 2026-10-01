# mypy: disable-error-code="arg-type, attr-defined, union-attr"
"""Backup & Restore view.

Features:
- Create backup now (prompts for folder, defaulting to configured folder).
- List all existing backups (size, date, contents, version).
- Restore from a selected backup with typed "RESTORE" confirmation; always
  creates a pre-restore safety backup first.
- Configure default backup folder and automatic-backup interval (days).
- Shows next scheduled backup date and a warning when one is due.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from dentiva.config import get_config, update_config
from dentiva.core.errors import PermissionDeniedError, ValidationError
from dentiva.core.permissions import Permission
from dentiva.services import backup_service
from dentiva.services.backup_service import RESTORE_CONFIRM_PHRASE
from dentiva.ui.design_tokens import Spacing
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class _BackupWorker(QThread):
    """Runs backup/restore off the UI thread."""
    progress = Signal(str, int, int)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, kind: str, payload: dict, parent=None) -> None:
        super().__init__(parent)
        self._kind = kind
        self._payload = payload

    def run(self) -> None:
        try:
            if self._kind == "backup":
                res = backup_service.create_backup(
                    self._payload["principal"],
                    target_dir=self._payload.get("target_dir"),
                    progress=lambda m, c, t: self.progress.emit(m, c, t),
                    include_attachments=self._payload.get("include_attachments", True),
                )
                self.finished_ok.emit(res)
            elif self._kind == "restore":
                res = backup_service.restore_backup(
                    self._payload["principal"],
                    Path(self._payload["backup_path"]),
                    confirmation=self._payload["confirmation"],
                    progress=lambda m, c, t: self.progress.emit(m, c, t),
                )
                self.finished_ok.emit(res)
            else:  # pragma: no cover
                self.failed.emit(f"Unknown operation {self._kind!r}.")
        except Exception as e:  # pragma: no cover - UI error path
            self.failed.emit(str(e))


class BackupView(QWidget):
    def __init__(self, session_factory, principal, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        self._worker: _BackupWorker | None = None
        self._build()
        self._reload()

    def refresh(self) -> None:
        self._reload()

    # -------------------------------------------------------------- build
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.S4)

        title = QLabel("Backup & Restore", self)
        title.setObjectName("DpPageTitle")
        sub = QLabel(
            "Create offline backups of your entire clinic database, attachments, "
            "and clinic logo. Restoring from a backup always creates a safety "
            "copy first.",
            self,
        )
        sub.setObjectName("DpPageSubtitle")
        sub.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(sub)

        # Status row: next scheduled + "backup now" button
        status_row = QHBoxLayout()
        self._status_label = QLabel("", self)
        self._status_label.setObjectName("DpHint")
        self._status_label.setWordWrap(True)
        status_row.addWidget(self._status_label, 1)
        self._backup_now_btn = QPushButton("Back up now…", self)
        self._backup_now_btn.setProperty("variant", "primary")
        self._backup_now_btn.clicked.connect(self._on_backup_now)
        self._backup_now_btn.setEnabled(self._p.has(Permission.BACKUP_CREATE) or self._p.is_superuser)
        status_row.addWidget(self._backup_now_btn)
        root.addLayout(status_row)

        # Progress bar (hidden when idle)
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        self._progress_text = QLabel("", self)
        self._progress_text.setVisible(False)
        root.addWidget(self._progress_text)
        root.addWidget(self._progress)

        # Backups list
        list_group = QGroupBox("Available backups", self)
        gl = QVBoxLayout(list_group)
        self._tbl = QTableWidget(0, 5, self)
        self._tbl.setObjectName("DpDataTable")
        self._tbl.setHorizontalHeaderLabels(["When", "Size", "DB", "Files", "Path"])
        self._tbl.setEditTriggers(self._tbl.EditTrigger(0))
        self._tbl.setSelectionBehavior(self._tbl.SelectionBehavior.SelectRows)
        self._tbl.setSelectionMode(self._tbl.SingleSelection)
        self._tbl.verticalHeader().setVisible(False)
        hh = self._tbl.horizontalHeader()
        hh.setSectionResizeMode(0, self._tbl.ResizeToContents)
        hh.setSectionResizeMode(1, self._tbl.ResizeToContents)
        hh.setSectionResizeMode(2, self._tbl.ResizeToContents)
        hh.setSectionResizeMode(3, self._tbl.ResizeToContents)
        hh.setSectionResizeMode(4, self._tbl.Stretch)
        gl.addWidget(self._tbl)

        btn_row = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh list", self)
        self._refresh_btn.clicked.connect(self._reload)
        self._open_folder_btn = QPushButton("Open backup folder", self)
        self._open_folder_btn.clicked.connect(self._on_open_folder)
        self._restore_btn = QPushButton("Restore selected…", self)
        self._restore_btn.setProperty("variant", "danger")
        self._restore_btn.clicked.connect(self._on_restore)
        self._restore_btn.setEnabled(self._p.has(Permission.BACKUP_RESTORE) or self._p.is_superuser)
        btn_row.addWidget(self._refresh_btn)
        btn_row.addWidget(self._open_folder_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._restore_btn)
        gl.addLayout(btn_row)
        root.addWidget(list_group, 1)

        # Settings group
        cfg_group = QGroupBox("Backup settings", self)
        cf = QFormLayout(cfg_group)
        folder_row = QHBoxLayout()
        self._folder_edit = QLineEdit(self)
        self._folder_edit.setReadOnly(True)
        self._folder_browse = QPushButton("Change…", self)
        self._folder_browse.clicked.connect(self._on_change_folder)
        self._folder_browse.setEnabled(self._p.has(Permission.BACKUP_CONFIGURE) or self._p.is_superuser)
        folder_row.addWidget(self._folder_edit, 1)
        folder_row.addWidget(self._folder_browse)
        fw = QWidget(self)
        fw.setLayout(folder_row)
        cf.addRow("Backup folder", fw)

        interval_row = QHBoxLayout()
        self._interval = QSpinBox(self)
        self._interval.setRange(0, 90)
        self._interval.setSuffix(" day(s)")
        self._interval.setSpecialValueText("Disabled")
        self._interval.setEnabled(self._p.has(Permission.BACKUP_CONFIGURE) or self._p.is_superuser)
        self._attachments = QCheckBox("Include attachments and logos in automatic backups", self)
        self._attachments.setChecked(True)
        # Attachments inclusion is always on (we always pack them) — the toggle
        # is a UI hint only for now.
        self._attachments.setEnabled(False)
        interval_row.addWidget(self._interval)
        interval_row.addStretch(1)
        cf.addRow("Automatic backup every", self._interval)
        cf.addRow(self._attachments)
        self._save_cfg_btn = QPushButton("Save settings", self)
        self._save_cfg_btn.setProperty("variant", "primary")
        self._save_cfg_btn.clicked.connect(self._on_save_settings)
        self._save_cfg_btn.setEnabled(self._p.has(Permission.BACKUP_CONFIGURE) or self._p.is_superuser)
        cf.addRow(self._save_cfg_btn)
        root.addWidget(cfg_group)

    # -------------------------------------------------------------- reload
    def _reload(self) -> None:
        cfg = get_config()
        folder = backup_service.default_backup_dir()
        self._folder_edit.setText(str(folder))
        self._interval.setValue(int(cfg.backup_interval_days))

        # Status text
        if backup_service.auto_backup_due():
            self._status_label.setText(
                "⚠ An automatic backup is due. Click \"Back up now\" to create one."
            )
        elif cfg.next_backup_at and cfg.backup_interval_days > 0:
            try:
                nxt = dt.datetime.fromisoformat(cfg.next_backup_at)
                self._status_label.setText(f"Next automatic backup scheduled for {nxt.strftime('%d %b %Y %H:%M')}.")
            except ValueError:
                self._status_label.setText("Automatic backups are enabled.")
        else:
            self._status_label.setText("Automatic backups are disabled.")

        entries = []
        can_list = (
            self._p.has(Permission.BACKUP_CREATE)
            or self._p.has(Permission.BACKUP_RESTORE)
            or self._p.is_superuser
        )
        if can_list:
            try:
                entries = backup_service.list_backups(self._p)
            except PermissionDeniedError:
                entries = []
        self._tbl.setRowCount(0)
        for e in entries:
            r = self._tbl.rowCount()
            self._tbl.insertRow(r)
            try:
                created = dt.datetime.fromisoformat(e["created_at"])
                when = created.strftime("%d %b %Y %H:%M")
            except ValueError:
                when = e["created_at"]
            self._tbl.setItem(r, 0, QTableWidgetItem(when))
            self._tbl.setItem(r, 1, QTableWidgetItem(backup_service.format_size(int(e["size_bytes"]))))
            self._tbl.setItem(r, 2, QTableWidgetItem(backup_service.format_size(int(e.get("db_size_bytes", 0)))))
            file_count = int(e.get("attachment_count", 0)) + int(e.get("logo_count", 0))
            self._tbl.setItem(r, 3, QTableWidgetItem(str(file_count)))
            self._tbl.setItem(r, 4, QTableWidgetItem(e.get("path", "")))
            if e.get("corrupt"):
                for c in range(5):
                    it = self._tbl.item(r, c)
                    if it is not None:
                        it.setForeground(Qt.red)

    # -------------------------------------------------------------- actions
    def _on_backup_now(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose backup destination folder", str(backup_service.default_backup_dir()),
        )
        if not folder:
            return
        target = Path(folder)
        self._start_worker("backup", {
            "principal": self._p, "target_dir": target, "include_attachments": True,
        })

    def _on_restore(self) -> None:
        row = self._tbl.currentRow()
        if row < 0:
            fn, _ = QFileDialog.getOpenFileName(
                self, "Select backup file to restore", str(backup_service.default_backup_dir()),
                "Dentiva backups (*.zip);;All files (*.*)",
            )
            if not fn:
                return
            backup_path = Path(fn)
        else:
            path_item = self._tbl.item(row, 4)
            if not path_item or not path_item.text():
                return
            backup_path = Path(path_item.text())

        # Confirmation dialog with typed phrase.
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setWindowTitle("Restore backup")
        msg_box.setText(
            "<b>Restoring will overwrite your current database, attachments, "
            "and clinic logo.</b><br><br>"
            "A safety backup will be created first, and the application must be "
            "restarted after the restore completes.<br><br>"
            f"To confirm, type <b>{RESTORE_CONFIRM_PHRASE}</b> below:"
        )
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, "Confirm restore",
            f"Type {RESTORE_CONFIRM_PHRASE} to restore from the selected backup:",
        )
        if not ok:
            return
        if text.strip() != RESTORE_CONFIRM_PHRASE:
            QMessageBox.warning(self, "Restore cancelled", "Confirmation phrase did not match.")
            return
        reply = QMessageBox.question(
            self, "Confirm restore",
            f"Restore from {backup_path.name}? This will replace all current data.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._start_worker("restore", {
            "principal": self._p, "backup_path": str(backup_path),
            "confirmation": RESTORE_CONFIRM_PHRASE,
        })

    def _on_open_folder(self) -> None:
        folder = str(backup_service.default_backup_dir())
        import os
        import sys
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", folder])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:  # pragma: no cover
            QMessageBox.information(self, "Backup folder", folder)

    def _on_change_folder(self) -> None:
        fn = QFileDialog.getExistingDirectory(self, "Choose default backup folder", self._folder_edit.text())
        if not fn:
            return
        try:
            backup_service.set_backup_dir(fn, self._p)
        except (ValidationError, PermissionDeniedError) as e:
            QMessageBox.warning(self, "Cannot change folder", str(getattr(e, "user_message", e)))
            return
        self._reload()

    def _on_save_settings(self) -> None:
        try:
            update_config(backup_interval_days=int(self._interval.value()))
        except Exception as e:  # pragma: no cover
            QMessageBox.warning(self, "Cannot save settings", str(e))
            return
        QMessageBox.information(self, "Backup settings", "Backup settings saved.")
        self._reload()

    def _start_worker(self, kind: str, payload: dict) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Busy", "Another backup/restore operation is running.")
            return
        self._progress.setVisible(True)
        self._progress_text.setVisible(True)
        self._progress_text.setText("Starting…")
        self._progress.setValue(0)
        self._set_buttons_enabled(False)
        self._worker = _BackupWorker(kind, payload, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(lambda r: self._on_finished(kind, r, None))
        self._worker.failed.connect(lambda msg: self._on_finished(kind, None, msg))
        self._worker.start()

    def _on_progress(self, msg: str, cur: int, tot: int) -> None:
        self._progress_text.setText(msg)
        pct = int(100 * cur / max(1, tot))
        self._progress.setValue(pct)

    def _on_finished(self, kind: str, result, error: str | None) -> None:
        self._set_buttons_enabled(True)
        self._progress.setVisible(False)
        self._progress_text.setVisible(False)
        self._worker = None
        if error:
            QMessageBox.critical(self, "Operation failed", error)
            return
        if kind == "backup":
            QMessageBox.information(
                self, "Backup complete",
                f"Backup saved to:\n{result.path}\n\n"
                f"Size: {backup_service.format_size(result.size_bytes)}  |  "
                f"Files: {result.file_count}",
            )
        elif kind == "restore":
            QMessageBox.warning(
                self, "Restore complete",
                f"Restore completed successfully.\n\n"
                f"Pre-restore safety backup saved to:\n{result.safety_backup}\n\n"
                "Please restart Dentiva Pro now to load the restored database.",
            )
        self._reload()

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self._backup_now_btn.setEnabled(
            enabled and (self._p.has(Permission.BACKUP_CREATE) or self._p.is_superuser)
        )
        self._restore_btn.setEnabled(
            enabled and (self._p.has(Permission.BACKUP_RESTORE) or self._p.is_superuser)
        )
        self._refresh_btn.setEnabled(enabled)
