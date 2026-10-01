"""QApplication bootstrap and application controller.

Wires together bootstrap → activation → setup → login → main window →
auto-lock. Authentication and activation are fully functional at Phase 3.
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog

from dentiva import __product_name__, __version__
from dentiva.auth.session import Session as UserSession
from dentiva.bootstrap import BootstrapResult, bootstrap
from dentiva.config import get_config, update_config
from dentiva.db.seed import seed_defaults
from dentiva.paths import paths
from dentiva.services.clinic_service import get_clinic
from dentiva.ui.dialogs import (
    ActivationDialog,
    LockDialog,
    LoginDialog,
    SetupWizard,
)
from dentiva.ui.main_window import MainWindow
from dentiva.ui.theme import apply_theme
from dentiva.ui.views.staff.staff_view import StaffUsersView

log = logging.getLogger(__name__)


def _load_icon() -> QIcon:
    icon = QIcon()
    ico = paths.app_icon_path
    if ico.exists():
        icon.addFile(str(ico))
    return icon


def _set_high_dpi_attributes() -> None:
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:  # pragma: no cover
        pass


class ApplicationController:
    """Owns the QApplication, bootstrap state, session and main window."""

    def __init__(self, argv: list[str]) -> None:
        self._argv = argv
        self._app: Optional[QApplication] = None
        self._main: Optional[MainWindow] = None
        self._boot: Optional[BootstrapResult] = None
        self._session = UserSession()
        self._lock_dialog: Optional[LockDialog] = None
        self._auto_lock_timer: Optional[QTimer] = None

    # ------------------------------------------------------------------ run
    def run(self) -> int:
        self._boot = bootstrap()

        _set_high_dpi_attributes()
        self._app = QApplication(self._argv)
        self._app.setApplicationName(__product_name__)
        self._app.setApplicationVersion(__version__)
        self._app.setOrganizationName("ShohanKhan")
        self._app.setWindowIcon(_load_icon())
        apply_theme(self._app)

        # Ensure seed data (payment methods, roles, teeth, clinical options)
        from dentiva.core.unit_of_work import UnitOfWork
        assert self._boot is not None
        with UnitOfWork(self._boot.session_factory) as uow:
            seed_defaults(uow.session)
            uow.commit()

        # 1. Activation
        if not self._boot.is_activated:
            dlg = ActivationDialog()
            if dlg.exec() != QDialog.Accepted:
                log.info("Activation declined; exiting.")
                return 0
            self._boot.is_activated = True

        # 2. First-run setup wizard
        if not self._boot.is_setup_complete:
            wizard = SetupWizard(self._boot.session_factory)
            wizard.exec()
            if not wizard.setup_succeeded():
                # User cancelled setup before completion; exit gracefully.
                return 0
            self._boot.is_setup_complete = True

        # 3. Login
        if not self._do_login():
            return 0

        # 4. Main window
        self._open_main_window()

        return self._app.exec()

    # ----------------------------------------------------------------- login
    def _do_login(self) -> bool:
        assert self._boot is not None
        cfg = get_config()
        dlg = LoginDialog(
            self._boot.session_factory,
            max_attempts=cfg.max_failed_login_attempts,
            lockout_minutes=cfg.failed_login_lockout_minutes,
        )
        # Pre-fill last user if configured.
        if cfg.last_logged_in_user:
            dlg._user_edit.setText(cfg.last_logged_in_user)
            dlg._pass_edit.setFocus()
        res = dlg.exec()
        if res != QDialog.Accepted or dlg.principal() is None:
            return False
        principal = dlg.principal()
        assert principal is not None
        self._session.login(principal, lock_minutes=cfg.autolock_minutes)
        update_config(last_logged_in_user=principal.username)
        return True

    # ----------------------------------------------------------------- main
    def _open_main_window(self) -> None:
        assert self._boot is not None and self._session.principal is not None
        from dentiva.core.unit_of_work import UnitOfWork
        boot = self._boot
        principal = self._session.principal
        clinic_name = ""
        with UnitOfWork(boot.session_factory) as uow:
            cp = get_clinic(uow.session)
            if cp:
                clinic_name = cp.name
        self._main = MainWindow(
            session_factory=boot.session_factory,
            principal=principal,
            clinic_name=clinic_name,
            display_name=principal.display_name,
        )
        # Replace the placeholder Staff & Users view with a real one because
        # that module is the one fully built in Phase 3. The rest are routed
        # through the PlaceholderView (Phase 2) until later phases.
        staff_view = StaffUsersView(boot.session_factory, principal, parent=self._main)
        self._main.replace_view("staff", staff_view)

        self._main.logout_requested.connect(self._on_logout)
        self._main.lock_requested.connect(lambda: self._lock(manual=True))
        self._main.quit_requested.connect(self._on_quit)

        # Auto-lock timer checks every 15 seconds.
        self._auto_lock_timer = QTimer(self._main)
        self._auto_lock_timer.timeout.connect(self._check_auto_lock)
        self._auto_lock_timer.start(15_000)

        # Connect user activity filter.
        self._main.on_user_activity_callbacks(self._on_user_activity)

        self._main.show()
        self._main.show_message(f"Welcome to {__product_name__}, {principal.display_name}.")

    def _on_user_activity(self) -> None:
        self._session.touch()

    def _check_auto_lock(self) -> None:
        if self._session.should_lock() and self._main is not None and self._main.isVisible():
            self._lock(manual=False)

    # ----------------------------------------------------------------- lock
    def _lock(self, *, manual: bool) -> None:
        if self._lock_dialog is not None and self._lock_dialog.isVisible():
            return
        if self._main is None or self._boot is None or self._session.principal is None:
            return
        boot = self._boot
        sess_principal = self._session.principal
        # In Phase 3 we do not yet do dirty-form save prompts (that comes with
        # data-entry forms in later phases); we just show the lock dialog.
        dlg = LockDialog(username=sess_principal.username, parent=self._main)
        self._lock_dialog = dlg
        while True:
            if dlg.exec() != QDialog.Accepted:
                # Logout or cancel → treat as logout.
                break
            # Verify password
            from dentiva.core.unit_of_work import UnitOfWork
            from dentiva.services import auth_service
            try:
                with UnitOfWork(boot.session_factory) as uow:
                    principal = auth_service.authenticate(
                        uow.session,
                        sess_principal.username,
                        dlg.password(),
                    )
                    uow.commit()
                # Same user → unlock.
                self._session.touch()
                self._main.show_message("Unlocked.", timeout=2000)
                return
            except Exception as e:
                dlg.show_error(getattr(e, "user_message", "Invalid password."))
        # Logout path.
        self._logout_and_return_to_login()

    # --------------------------------------------------------------- logout
    def _on_logout(self) -> None:
        self._session.logout()
        self._logout_and_return_to_login()

    def _logout_and_return_to_login(self) -> None:
        if self._main is not None:
            self._main.hide()
            self._main.close()
            self._main = None
        if self._auto_lock_timer is not None:
            self._auto_lock_timer.stop()
            self._auto_lock_timer = None
        if not self._do_login():
            app_instance = QApplication.instance()
            if app_instance is not None:
                app_instance.quit()
            return
        self._open_main_window()

    def _on_quit(self) -> None:
        log.info("Quit requested.")
        # Close DB engine cleanly.
        if self._boot is not None:
            try:
                self._boot.engine.dispose()
            except Exception:  # pragma: no cover
                pass


def run(argv: list[str]) -> int:
    """Module-level entry point used by ``python -m dentiva`` and console script."""
    controller = ApplicationController(argv)
    return controller.run()
