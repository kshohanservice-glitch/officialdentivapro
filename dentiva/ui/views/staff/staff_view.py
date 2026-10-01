# mypy: disable-error-code="arg-type, attr-defined, union-attr"
"""Staff & Users view — users, roles, and dentists (clinical providers)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from dentiva.core.errors import DentivaError, ValidationError
from dentiva.core.permissions import Permission
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.services import dentist_service, user_service
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    pass


# ------------------------------------------------------------------------- User dialogs


class UserEditDialog(QDialog):
    def __init__(self, session_factory, principal, *, user=None, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        self._user = user  # None = create new
        self.setWindowTitle("Edit user" if user else "Create user")
        self.setMinimumWidth(420)
        self.setModal(True)
        f = QFormLayout(self)
        self._username = QLineEdit(self)
        self._display = QLineEdit(self)
        self._pass = QLineEdit(self)
        self._pass.setEchoMode(QLineEdit.Password)
        self._pass.setPlaceholderText("Leave blank to keep unchanged" if user else "Required for new users")
        self._role = QComboBox(self)
        self._active = QCheckBox("Account active", self)
        self._active.setChecked(True)
        with UnitOfWork(session_factory) as uow:
            roles = user_service.list_roles(uow.session, principal)
        for r in roles:
            self._role.addItem(r.name, r.id)
        self._role.addItem("(no role)", None)
        if user is not None:
            self._username.setText(user.username)
            self._display.setText(user.display_name)
            idx = self._role.findData(user.role_id)
            if idx >= 0:
                self._role.setCurrentIndex(idx)
            self._active.setChecked(user.is_active)
        f.addRow("Username *", self._username)
        f.addRow("Display name", self._display)
        f.addRow("Password" if user else "Password *", self._pass)
        f.addRow("Role", self._role)
        if user is not None and principal.has(Permission.USERS_EDIT):
            f.addRow("", self._active)
        self._err = QLabel("", self)
        self._err.setObjectName("DpFieldError")
        self._err.setWordWrap(True)
        f.addRow(self._err)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _save(self) -> None:
        self._err.setText("")
        username = self._username.text().strip()
        display = self._display.text().strip()
        password = self._pass.text()
        role_id = self._role.currentData()
        try:
            with UnitOfWork(self._sf) as uow:
                if self._user is None:
                    from dentiva.services.auth_service import create_user
                    if not password or len(password) < 6:
                        raise ValidationError("Password must be at least 6 characters.", field="password")
                    create_user(uow.session, self._p, username=username, password=password,
                                display_name=display, role_id=role_id)
                else:
                    user_service.update_user(uow.session, self._p, self._user.id,
                                             display_name=display, username=username)
                    user_service.set_user_role(uow.session, self._p, self._user.id, role_id)
                    if password:
                        user_service.reset_password(uow.session, self._p, self._user.id, password)
                    if self._active.isChecked() and not self._user.is_active:
                        user_service.activate_user(uow.session, self._p, self._user.id)
                    elif not self._active.isChecked() and self._user.is_active:
                        user_service.deactivate_user(uow.session, self._p, self._user.id)
                uow.commit()
        except ValidationError as e:
            self._err.setText(e.user_message)
            return
        except DentivaError as e:
            self._err.setText(e.user_message)
            return
        self.accept()


# ------------------------------------------------------------------------- Role dialog


class RoleDialog(QDialog):
    def __init__(self, session_factory, principal, *, role=None, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        self._role = role
        self.setWindowTitle("Edit role" if role else "New role")
        self.setMinimumWidth(520)
        self.setModal(True)
        v = QVBoxLayout(self)
        f = QFormLayout()
        self._name = QLineEdit(self)
        self._desc = QLineEdit(self)
        if role is not None:
            self._name.setText(role.name)
            self._desc.setText(role.description)
        f.addRow("Name *", self._name)
        f.addRow("Description", self._desc)
        v.addLayout(f)
        if role is not None and role.is_system:
            warn = QLabel("This is a system role and cannot be edited. Clone it to customize.", self)
            warn.setObjectName("DpFieldError")
            warn.setWordWrap(True)
            v.addWidget(warn)
            self._name.setEnabled(False)
            self._desc.setEnabled(False)
        box = QGroupBox("Permissions", self)
        grid = QVBoxLayout(box)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self._perm_layout = QVBoxLayout(inner)
        self._checks: dict[str, QCheckBox] = {}
        current = set(role.permissions) if role is not None else set()
        last_group = None
        group_box = None
        group_layout = None
        for perm_value, group, label in user_service.available_permissions():
            if group != last_group:
                group_box = QGroupBox(group, inner)
                group_layout = QVBoxLayout(group_box)
                self._perm_layout.addWidget(group_box)
                last_group = group
            cb = QCheckBox(label, group_box)
            cb.setChecked(perm_value in current)
            cb.setProperty("perm", perm_value)
            if role is not None and role.is_system:
                cb.setEnabled(False)
            self._checks[perm_value] = cb
            group_layout.addWidget(cb)
        scroll.setWidget(inner)
        grid.addWidget(scroll)
        v.addWidget(box, 1)
        self._err = QLabel("", self)
        self._err.setObjectName("DpFieldError")
        self._err.setWordWrap(True)
        v.addWidget(self._err)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        save_btn = bb.button(QDialogButtonBox.Save)
        if role is not None and role.is_system:
            save_btn.setEnabled(False)
        v.addWidget(bb)

    def _save(self) -> None:
        self._err.setText("")
        perms = [p for p, cb in self._checks.items() if cb.isChecked()]
        try:
            with UnitOfWork(self._sf) as uow:
                if self._role is None:
                    user_service.create_role(uow.session, self._p,
                                             name=self._name.text().strip(),
                                             description=self._desc.text().strip(),
                                             permissions=perms)
                else:
                    user_service.update_role(uow.session, self._p, self._role.id,
                                             name=self._name.text().strip(),
                                             description=self._desc.text().strip(),
                                             permissions=perms)
                uow.commit()
        except ValidationError as e:
            self._err.setText(e.user_message)
            return
        except DentivaError as e:
            self._err.setText(e.user_message)
            return
        self.accept()


# ------------------------------------------------------------------------- Dentist dialog


class DentistDialog(QDialog):
    def __init__(self, session_factory, principal, *, dentist=None, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        self._dentist = dentist
        self.setWindowTitle("Edit provider" if dentist else "New provider")
        self.setMinimumWidth(400)
        self.setModal(True)
        f = QFormLayout(self)
        self._name = QLineEdit(self)
        self._phone = QLineEdit(self)
        self._email = QLineEdit(self)
        self._designations = QLineEdit(self)
        self._designations.setPlaceholderText("Comma-separated: BDS, FCPS, …")
        if dentist is not None:
            self._name.setText(dentist.name)
            self._phone.setText(dentist.phone or "")
            self._email.setText(dentist.email or "")
            self._designations.setText(", ".join(d.name for d in dentist.designations))
        f.addRow("Name *", self._name)
        f.addRow("Phone", self._phone)
        f.addRow("Email", self._email)
        f.addRow("Designations", self._designations)
        self._err = QLabel("", self)
        self._err.setObjectName("DpFieldError")
        self._err.setWordWrap(True)
        f.addRow(self._err)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _save(self) -> None:
        self._err.setText("")
        name = self._name.text().strip()
        if not name:
            self._err.setText("Name is required.")
            return
        desigs = [d.strip() for d in self._designations.text().split(",") if d.strip()]
        try:
            with UnitOfWork(self._sf) as uow:
                if self._dentist is None:
                    dentist_service.create_dentist(
                        uow.session, self._p,
                        name=name, phone=self._phone.text().strip(),
                        email=self._email.text().strip(), designations=desigs,
                    )
                else:
                    dentist_service.update_dentist(
                        uow.session, self._p, self._dentist.id,
                        name=name, phone=self._phone.text().strip(),
                        email=self._email.text().strip(), designations=desigs,
                    )
                uow.commit()
        except ValidationError as e:
            self._err.setText(e.user_message)
            return
        except DentivaError as e:
            self._err.setText(e.user_message)
            return
        self.accept()


# ------------------------------------------------------------------------- Users tab


class UsersTab(QWidget):
    users_changed = Signal()

    def __init__(self, session_factory, principal, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self._add_btn = QPushButton("New user", self)
        self._add_btn.setProperty("variant", "primary")
        self._add_btn.clicked.connect(self._on_add)
        self._add_btn.setVisible(self._p.has(Permission.USERS_CREATE))
        self._edit_btn = QPushButton("Edit", self)
        self._edit_btn.clicked.connect(self._on_edit)
        self._edit_btn.setVisible(self._p.has(Permission.USERS_EDIT))
        self._reset_btn = QPushButton("Reset password", self)
        self._reset_btn.clicked.connect(self._on_reset)
        self._reset_btn.setVisible(self._p.has(Permission.USERS_RESET_PASSWORD))
        self._act_btn = QPushButton("Activate/Deactivate", self)
        self._act_btn.clicked.connect(self._on_toggle_active)
        self._act_btn.setVisible(self._p.has(Permission.USERS_EDIT))
        refresh = QPushButton("Refresh", self)
        refresh.clicked.connect(self.refresh)
        bar.addStretch(1)
        bar.addWidget(self._add_btn)
        bar.addWidget(self._edit_btn)
        bar.addWidget(self._reset_btn)
        bar.addWidget(self._act_btn)
        bar.addWidget(refresh)
        v.addLayout(bar)

        self._tbl = QTableWidget(0, 6, self)
        self._tbl.setObjectName("DpDataTable")
        self._tbl.setHorizontalHeaderLabels(["Username", "Display name", "Role", "Status", "Must change pw", "Last login"])
        self._tbl.setEditTriggers(self._tbl.EditTrigger(0))
        self._tbl.setSelectionBehavior(self._tbl.SelectionBehavior.SelectRows)
        self._tbl.setSelectionMode(self._tbl.SelectionMode.SingleSelection)
        self._tbl.verticalHeader().setVisible(False)
        hh = self._tbl.horizontalHeader()
        for c, mode in enumerate([
            QHeaderView.ResizeToContents, QHeaderView.Stretch, QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents, QHeaderView.ResizeToContents, QHeaderView.ResizeToContents,
        ]):
            hh.setSectionResizeMode(c, mode)
        self._tbl.doubleClicked.connect(lambda _i: self._on_edit() if self._p.has(Permission.USERS_EDIT) else None)
        v.addWidget(self._tbl, 1)
        self.refresh()

    def refresh(self) -> None:
        try:
            with UnitOfWork(self._sf) as uow:
                users = user_service.list_users(uow.session, self._p)
        except DentivaError:
            return
        self._tbl.setRowCount(len(users))
        for row, u in enumerate(users):
            self._tbl.setItem(row, 0, QTableWidgetItem(u.username))
            self._tbl.setItem(row, 1, QTableWidgetItem(u.display_name))
            role_item = QTableWidgetItem(u.role_name + (" (superuser)" if u.is_superuser else ""))
            self._tbl.setItem(row, 2, role_item)
            status = QTableWidgetItem("Active" if u.is_active else "Inactive")
            if not u.is_active:
                status.setForeground(Qt.GlobalColor.gray)
            self._tbl.setItem(row, 3, status)
            self._tbl.setItem(row, 4, QTableWidgetItem("Yes" if u.must_change_password else ""))
            ll = u.last_login_at
            self._tbl.setItem(row, 5, QTableWidgetItem(ll.strftime("%Y-%m-%d %H:%M") if ll else "Never"))
            self._tbl.item(row, 0).setData(Qt.UserRole, u.id)

    def _selected_user_id(self):
        row = self._tbl.currentRow()
        if row < 0:
            return None
        it = self._tbl.item(row, 0)
        return int(it.data(Qt.UserRole)) if it else None

    def _selected_row(self):
        uid = self._selected_user_id()
        if uid is None:
            return None
        with UnitOfWork(self._sf) as uow:
            users = user_service.list_users(uow.session, self._p)
        for u in users:
            if u.id == uid:
                return u
        return None

    def _on_add(self) -> None:
        if UserEditDialog(self._sf, self._p, parent=self).exec():
            self.refresh()
            self.users_changed.emit()

    def _on_edit(self) -> None:
        u = self._selected_row()
        if u is None:
            QMessageBox.information(self, "Edit", "Select a user first.")
            return
        if UserEditDialog(self._sf, self._p, user=u, parent=self).exec():
            self.refresh()
            self.users_changed.emit()

    def _on_reset(self) -> None:
        u = self._selected_row()
        if u is None:
            QMessageBox.information(self, "Reset password", "Select a user first.")
            return
        text, ok = QInputDialog.getText(self, "Reset password", "New password (min 6 chars):", QLineEdit.Password)
        if not ok or not text:
            return
        try:
            with UnitOfWork(self._sf) as uow:
                user_service.reset_password(uow.session, self._p, u.id, text)
                uow.commit()
            QMessageBox.information(self, "Password reset", "Password has been reset.")
        except (DentivaError, ValidationError) as e:
            QMessageBox.critical(self, "Error", e.user_message)

    def _on_toggle_active(self) -> None:
        u = self._selected_row()
        if u is None:
            QMessageBox.information(self, "Activate/Deactivate", "Select a user first.")
            return
        if u.is_active:
            if QMessageBox.question(self, "Deactivate", f"Deactivate user '{u.username}'?") != QMessageBox.Yes:
                return
            try:
                with UnitOfWork(self._sf) as uow:
                    user_service.deactivate_user(uow.session, self._p, u.id)
                    uow.commit()
            except (DentivaError, ValidationError) as e:
                QMessageBox.critical(self, "Error", e.user_message)
                return
        else:
            try:
                with UnitOfWork(self._sf) as uow:
                    user_service.activate_user(uow.session, self._p, u.id)
                    uow.commit()
            except (DentivaError, ValidationError) as e:
                QMessageBox.critical(self, "Error", e.user_message)
                return
        self.refresh()


# ------------------------------------------------------------------------- Roles tab


class RolesTab(QWidget):
    def __init__(self, session_factory, principal, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self._add_btn = QPushButton("New role", self)
        self._add_btn.setProperty("variant", "primary")
        self._add_btn.clicked.connect(self._on_new)
        self._add_btn.setVisible(self._p.has(Permission.ROLES_MANAGE))
        self._edit_btn = QPushButton("View / Edit", self)
        self._edit_btn.clicked.connect(self._on_edit)
        refresh = QPushButton("Refresh", self)
        refresh.clicked.connect(self.refresh)
        bar.addStretch(1)
        bar.addWidget(self._add_btn)
        bar.addWidget(self._edit_btn)
        bar.addWidget(refresh)
        v.addLayout(bar)
        self._tbl = QTableWidget(0, 3, self)
        self._tbl.setObjectName("DpDataTable")
        self._tbl.setHorizontalHeaderLabels(["Role", "Description", "System"])
        self._tbl.setEditTriggers(self._tbl.EditTrigger(0))
        self._tbl.setSelectionBehavior(self._tbl.SelectionBehavior.SelectRows)
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._tbl.doubleClicked.connect(lambda _i: self._on_edit())
        v.addWidget(self._tbl, 1)
        self.refresh()

    def refresh(self) -> None:
        try:
            with UnitOfWork(self._sf) as uow:
                roles = user_service.list_roles(uow.session, self._p)
        except DentivaError:
            return
        self._tbl.setRowCount(len(roles))
        for row, r in enumerate(roles):
            self._tbl.setItem(row, 0, QTableWidgetItem(r.name))
            self._tbl.setItem(row, 1, QTableWidgetItem(r.description))
            sys_it = QTableWidgetItem("System" if r.is_system else "Custom")
            if r.is_system:
                sys_it.setForeground(Qt.GlobalColor.gray)
            self._tbl.setItem(row, 2, sys_it)
            self._tbl.item(row, 0).setData(Qt.UserRole, r.id)

    def _selected_id(self):
        row = self._tbl.currentRow()
        if row < 0:
            return None
        it = self._tbl.item(row, 0)
        return int(it.data(Qt.UserRole)) if it else None

    def _selected_role(self):
        rid = self._selected_id()
        if rid is None:
            return None
        with UnitOfWork(self._sf) as uow:
            roles = user_service.list_roles(uow.session, self._p)
        for r in roles:
            if r.id == rid:
                return r
        return None

    def _on_new(self) -> None:
        if RoleDialog(self._sf, self._p, parent=self).exec():
            self.refresh()

    def _on_edit(self) -> None:
        r = self._selected_role()
        if r is None:
            QMessageBox.information(self, "Role", "Select a role first.")
            return
        RoleDialog(self._sf, self._p, role=r, parent=self).exec()
        self.refresh()


# ------------------------------------------------------------------------- Dentists tab


class DentistsTab(QWidget):
    def __init__(self, session_factory, principal, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self._add_btn = QPushButton("New provider", self)
        self._add_btn.setProperty("variant", "primary")
        self._add_btn.clicked.connect(self._on_add)
        can_manage = principal.has(Permission.DENTISTS_MANAGE)
        self._add_btn.setVisible(can_manage)
        self._edit_btn = QPushButton("Edit", self)
        self._edit_btn.clicked.connect(self._on_edit)
        self._edit_btn.setVisible(can_manage)
        refresh = QPushButton("Refresh", self)
        refresh.clicked.connect(self.refresh)
        bar.addStretch(1)
        bar.addWidget(self._add_btn)
        bar.addWidget(self._edit_btn)
        bar.addWidget(refresh)
        v.addLayout(bar)
        self._tbl = QTableWidget(0, 4, self)
        self._tbl.setObjectName("DpDataTable")
        self._tbl.setHorizontalHeaderLabels(["Name", "Designations", "Phone", "Email"])
        self._tbl.setEditTriggers(self._tbl.EditTrigger(0))
        self._tbl.setSelectionBehavior(self._tbl.SelectionBehavior.SelectRows)
        self._tbl.verticalHeader().setVisible(False)
        hh = self._tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self._tbl.doubleClicked.connect(lambda _i: self._on_edit() if can_manage else None)
        v.addWidget(self._tbl, 1)
        self.refresh()

    def refresh(self) -> None:
        try:
            with UnitOfWork(self._sf) as uow:
                dentists = dentist_service.list_dentists(uow.session, self._p, include_inactive=True)
        except DentivaError:
            return
        self._tbl.setRowCount(len(dentists))
        for row, d in enumerate(dentists):
            self._tbl.setItem(row, 0, QTableWidgetItem(d.name))
            des = ", ".join(x.name for x in d.designations)
            self._tbl.setItem(row, 1, QTableWidgetItem(des))
            self._tbl.setItem(row, 2, QTableWidgetItem(d.phone or ""))
            self._tbl.setItem(row, 3, QTableWidgetItem(d.email or ""))
            self._tbl.item(row, 0).setData(Qt.UserRole, d.id)

    def _selected(self):
        row = self._tbl.currentRow()
        if row < 0:
            return None
        it = self._tbl.item(row, 0)
        if it is None:
            return None
        did = int(it.data(Qt.UserRole))
        with UnitOfWork(self._sf) as uow:
            return dentist_service.get_dentist(uow.session, did)

    def _on_add(self) -> None:
        if DentistDialog(self._sf, self._p, parent=self).exec():
            self.refresh()

    def _on_edit(self) -> None:
        d = self._selected()
        if d is None:
            QMessageBox.information(self, "Edit", "Select a provider first.")
            return
        if DentistDialog(self._sf, self._p, dentist=d, parent=self).exec():
            self.refresh()


# ------------------------------------------------------------------------- Main view


class StaffUsersView(QWidget):
    def __init__(self, session_factory, principal, parent=None) -> None:
        super().__init__(parent)
        self._sf = session_factory
        self._p = principal
        v = QVBoxLayout(self)
        title = QLabel("Staff, users & roles", self)
        title.setObjectName("DpPageTitle")
        sub = QLabel("Manage user accounts, access roles, and clinical providers (dentists).", self)
        sub.setObjectName("DpPageSubtitle")
        v.addWidget(title)
        v.addWidget(sub)
        tabs = QTabWidget(self)
        self._users = UsersTab(session_factory, principal, self)
        self._roles = RolesTab(session_factory, principal, self)
        self._dentists = DentistsTab(session_factory, principal, self)
        tabs.addTab(self._users, "Users")
        tabs.addTab(self._roles, "Roles")
        tabs.addTab(self._dentists, "Providers (Dentists)")
        v.addWidget(tabs, 1)

    def refresh(self) -> None:
        self._users.refresh()
        self._roles.refresh()
        self._dentists.refresh()
