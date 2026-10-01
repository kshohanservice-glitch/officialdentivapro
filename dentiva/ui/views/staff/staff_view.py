"""Staff & Users view: user list, role assignment, password reset, deactivate.

Phase 3: users tab (fully functional). Staff tab is a placeholder for
Phase 11 which adds full employee records.
"""
from __future__ import annotations

from dentiva.core.errors import DentivaError, ValidationError
from dentiva.core.permissions import Permission, Principal
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.models import Role
from dentiva.services import user_service
from dentiva.ui.widgets.placeholder import PlaceholderView
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select


class UserCreateDialog(QDialog):
    def __init__(self, session_factory, principal: Principal, parent=None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal
        self.setWindowTitle("Create user")
        self.setMinimumWidth(400)
        v = QVBoxLayout(self)
        form = QFormLayout()
        self._user = QLineEdit(self)
        self._display = QLineEdit(self)
        self._pass = QLineEdit(self)
        self._pass.setEchoMode(QLineEdit.Password)
        self._role = QComboBox(self)
        with UnitOfWork(self._session_factory) as uow:
            roles = list(uow.session.scalars(select(Role).order_by(Role.name)))
        for r in roles:
            self._role.addItem(r.name, r.id)
        form.addRow("Username *", self._user)
        form.addRow("Display name", self._display)
        form.addRow("Password *", self._pass)
        form.addRow("Role", self._role)
        v.addLayout(form)
        self._err = QLabel("", self)
        self._err.setStyleSheet("color:#F04438;")
        v.addWidget(self._err)
        btns = QHBoxLayout()
        btns.addStretch(1)
        c = QPushButton("Cancel", self)
        c.clicked.connect(self.reject)
        ok = QPushButton("Create", self)
        ok.setProperty("variant", "primary")
        ok.clicked.connect(self._save)
        btns.addWidget(c)
        btns.addWidget(ok)
        v.addLayout(btns)

    def _save(self) -> None:
        from dentiva.services.auth_service import create_user
        try:
            with UnitOfWork(self._session_factory) as uow:
                create_user(
                    uow.session,
                    self._principal,
                    username=self._user.text(),
                    password=self._pass.text(),
                    display_name=self._display.text(),
                    role_id=self._role.currentData(),
                )
                uow.commit()
            self.accept()
        except (DentivaError, ValidationError) as e:
            self._err.setText(e.user_message)


class UsersTab(QWidget):
    users_changed = Signal()

    def __init__(self, session_factory, principal: Principal, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)

        bar = QHBoxLayout()
        title = QLabel("Users", self)
        title.setStyleSheet("font-size:16pt; font-weight:600;")
        bar.addWidget(title)
        bar.addStretch(1)
        self._add_btn = QPushButton("New user", self)
        self._add_btn.setProperty("variant", "primary")
        self._add_btn.clicked.connect(self._add_user)
        self._add_btn.setEnabled(self._principal.has(Permission.USERS_CREATE))
        self._reset_btn = QPushButton("Reset password", self)
        self._reset_btn.clicked.connect(self._reset_password)
        self._reset_btn.setEnabled(self._principal.has(Permission.USERS_RESET_PASSWORD))
        self._deact_btn = QPushButton("Deactivate", self)
        self._deact_btn.setProperty("variant", "destructive")
        self._deact_btn.clicked.connect(self._deactivate)
        self._deact_btn.setEnabled(self._principal.has(Permission.USERS_EDIT))
        self._refresh_btn = QPushButton("Refresh", self)
        self._refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(self._add_btn)
        bar.addWidget(self._reset_btn)
        bar.addWidget(self._deact_btn)
        bar.addWidget(self._refresh_btn)
        v.addLayout(bar)

        self._table = QTableWidget(0, 5, self)
        self._table.setObjectName("DpDataTable")
        self._table.setHorizontalHeaderLabels(["Username", "Display name", "Role", "Status", "Last login"])
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        v.addWidget(self._table, 1)

        self.refresh()

    def refresh(self) -> None:
        try:
            with UnitOfWork(self._session_factory) as uow:
                users = user_service.list_users(uow.session, self._principal)
                roles = {r.id: r.name for r in user_service.list_roles(uow.session, self._principal)}
        except PermissionError:
            return
        self._table.setRowCount(len(users))
        for row, u in enumerate(users):
            self._table.setItem(row, 0, QTableWidgetItem(u.username))
            self._table.setItem(row, 1, QTableWidgetItem(u.display_name or ""))
            self._table.setItem(row, 2, QTableWidgetItem(roles.get(u.role_id, "—") if u.role_id else "—"))
            self._table.setItem(row, 3, QTableWidgetItem("Active" if u.is_active else "Inactive"))
            self._table.setItem(row, 4, QTableWidgetItem(u.last_login_at.strftime("%Y-%m-%d %H:%M") if u.last_login_at else "Never"))
            # store user id in first column
            self._table.item(row, 0).setData(Qt.UserRole, u.id)

    def _selected_user_id(self) -> int | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        return int(item.data(Qt.UserRole)) if item else None

    def _add_user(self) -> None:
        dlg = UserCreateDialog(self._session_factory, self._principal, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh()
            self.users_changed.emit()

    def _reset_password(self) -> None:
        uid = self._selected_user_id()
        if uid is None:
            QMessageBox.information(self, "Reset password", "Select a user first.")
            return
        text, ok = _prompt_text(self, "Reset password", "New password (min 6 chars):", password=True)
        if not ok or not text:
            return
        try:
            with UnitOfWork(self._session_factory) as uow:
                user_service.reset_password(uow.session, self._principal, uid, text)
                uow.commit()
            QMessageBox.information(self, "Password reset", "Password has been reset.")
        except (DentivaError, ValidationError) as e:
            QMessageBox.critical(self, "Error", e.user_message)

    def _deactivate(self) -> None:
        uid = self._selected_user_id()
        if uid is None:
            QMessageBox.information(self, "Deactivate", "Select a user first.")
            return
        reply = QMessageBox.question(self, "Deactivate user",
                                     "Deactivate the selected user? They will no longer be able to sign in.",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            with UnitOfWork(self._session_factory) as uow:
                user_service.deactivate_user(uow.session, self._principal, uid)
                uow.commit()
            self.refresh()
        except (DentivaError, ValidationError) as e:
            QMessageBox.critical(self, "Error", e.user_message)


from PySide6.QtWidgets import QInputDialog  # noqa: E402


def _prompt_text(parent, title: str, label: str, *, password: bool = False):
    mode = QLineEdit.Password if password else QLineEdit.Normal
    text, ok = QInputDialog.getText(parent, title, label, mode)
    return text, ok


class StaffUsersView(QWidget):
    def __init__(self, session_factory, principal: Principal, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._principal = principal
        v = QVBoxLayout(self)
        tabs = QTabWidget(self)
        self._users = UsersTab(session_factory, principal, self)
        self._staff = PlaceholderView("Staff", "Employee records module will be completed in Phase 11.", self)
        tabs.addTab(self._users, "Users")
        tabs.addTab(self._staff, "Staff")
        v.addWidget(tabs)
