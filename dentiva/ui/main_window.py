"""Main application window (shell): header + collapsible sidebar + stack."""
from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from dentiva import __product_name__, __version__
from dentiva.core.permissions import Principal
from dentiva.ui.design_tokens import Shell, Spacing
from dentiva.ui.navigation import title_for, view_for
from dentiva.ui.widgets.header import Header
from dentiva.ui.widgets.nav import Sidebar
from dentiva.ui.widgets.notifications_popup import NotificationsPopup
from dentiva.ui.widgets.search_popup import GlobalSearchPopup

log = logging.getLogger(__name__)


class _ActivityFilter(QWidget):
    """Event filter that emits :pyattr:`activity_detected` on user input."""

    activity_detected = Signal()

    def eventFilter(self, watched, event):  # type: ignore[override]
        etype = event.type()
        if etype in (
            QEvent.KeyPress,
            QEvent.MouseButtonPress,
            QEvent.MouseMove,
            QEvent.Wheel,
            QEvent.FocusIn,
        ):
            self.activity_detected.emit()
        return super().eventFilter(watched, event)


class MainWindow(QMainWindow):
    """Dentiva Pro primary application shell."""

    logout_requested = Signal()
    lock_requested = Signal()
    quit_requested = Signal()
    navigate = Signal(str)  # route name, for cross-component nav requests

    def __init__(
        self,
        *,
        session_factory,
        principal: Principal,
        clinic_name: str = "",
        display_name: str = "",
    ) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._principal = principal
        self.setWindowTitle(f"{__product_name__} v{__version__}")
        self.setMinimumSize(1024, 640)
        self.resize(1280, 800)

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        self._header = Header(self)
        self._header.set_clinic_name(clinic_name)
        self._header.set_user_display(display_name)
        self._header.toggle_sidebar.connect(self.toggle_sidebar)
        self._header.logout_requested.connect(self._confirm_logout)
        self._header.lock_requested.connect(self.lock_requested.emit)
        root.addWidget(self._header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Sidebar
        self._sidebar = Sidebar(self)
        self._sidebar.nav_selected.connect(self.navigate_to)
        body.addWidget(self._sidebar)

        # Content area: a vertical layout with a scrollable stacked widget.
        content_wrap = QWidget(self)
        content_wrap.setObjectName("DpContentArea")
        content_layout = QVBoxLayout(content_wrap)
        content_layout.setContentsMargins(
            Shell.CONTENT_PADDING, Shell.CONTENT_PADDING, Shell.CONTENT_PADDING, Shell.CONTENT_PADDING
        )
        content_layout.setSpacing(Spacing.S4)

        self._scroll = QScrollArea(content_wrap)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QWidget.NoFrame)
        self._stack = QStackedWidget(self._scroll)
        self._scroll.setWidget(self._stack)
        content_layout.addWidget(self._scroll, 1)

        body.addWidget(content_wrap, 1)
        root.addLayout(body, 1)

        # Status bar
        self._status = QStatusBar(self)
        self.setStatusBar(self._status)
        self.show_message("Ready")

        # Activity filter for auto-lock
        self._activity = _ActivityFilter(self)
        self.installEventFilter(self._activity)
        self._activity.activity_detected.connect(self._on_user_activity)

        # Keyboard shortcuts
        self._shortcut_lock = QShortcut(QKeySequence("Ctrl+L"), self)
        self._shortcut_lock.activated.connect(self.lock_requested.emit)
        self._shortcut_toggle = QShortcut(QKeySequence("Ctrl+B"), self)
        self._shortcut_toggle.activated.connect(self.toggle_sidebar)
        # Popovers (global search + notifications). They are children of the
        # central widget so they float over the content area.
        self._search_popup = GlobalSearchPopup(self._session_factory, self._principal, parent=central)
        self._search_popup.result_selected.connect(self._on_search_result)
        self._search_popup.dismissed.connect(lambda: self._search_popup.hide())

        self._notif_popup = NotificationsPopup(self._session_factory, self._principal, parent=central)
        self._header.notifications_requested.connect(self._toggle_notifications)

        # Pre-populate every route in the stack so back/forward is instant and
        # there are no dead buttons.
        self._views: dict[str, QWidget] = {}
        for key in ("dashboard", "patients", "appointments", "queue", "treatments",
                    "prescriptions", "invoices", "payments", "inventory", "accounting",
                    "staff", "backup", "settings", "about"):
            widget = view_for(key, parent=self._stack)
            self._stack.addWidget(widget)
            self._views[key] = widget        # Replace placeholder views with their live implementations now that
        # we have an authenticated principal and session factory.
        from dentiva.ui.views.dashboard.dashboard_view import DashboardView
        self.replace_view("dashboard", DashboardView(self._session_factory, self._principal, parent=self._stack))

        from dentiva.ui.views.appointments.appointments_view import AppointmentsView
        appointments_view = AppointmentsView(self._session_factory, self._principal, parent=self._stack)
        self.replace_view("appointments", appointments_view)

        from dentiva.ui.views.patients.patients_view import PatientsView
        patients_view = PatientsView(self._session_factory, self._principal, parent=self._stack)
        patients_view.patient_opened.connect(self.open_patient_profile)
        self.replace_view("patients", patients_view)
        self._patients_view = patients_view

        from dentiva.ui.views.treatments.treatments_view import TreatmentsView
        self.replace_view("treatments", TreatmentsView(self._session_factory, self._principal, parent=self._stack))

        from dentiva.ui.views.prescriptions.prescriptions_view import PrescriptionsView
        self.replace_view("prescriptions", PrescriptionsView(self._session_factory, self._principal, parent=self._stack))

        from dentiva.ui.views.invoices.invoices_view import InvoicesView
        self.replace_view("invoices", InvoicesView(self._session_factory, self._principal, parent=self._stack))

        from dentiva.ui.views.payments.payments_view import PaymentsView
        self.replace_view("payments", PaymentsView(self._session_factory, self._principal, parent=self._stack))

        from dentiva.ui.views.inventory.inventory_view import InventoryView
        self.replace_view("inventory", InventoryView(self._session_factory, self._principal, parent=self._stack))

        from dentiva.ui.views.accounting.accounting_view import AccountingView
        self.replace_view("accounting", AccountingView(self._session_factory, self._principal, parent=self._stack))

        # Notification badge refresh timer (every 30 seconds).
        self._notif_timer = QTimer(self)
        self._notif_timer.timeout.connect(self._refresh_notif_badge)
        self._notif_timer.start(30_000)
        self._refresh_notif_badge()

        self.navigate_to("dashboard")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_clock)
        self._timer.start(10_000)  # update header date/time every 10s

    # ---------- public API ----------

    def show_message(self, text: str, timeout: int = 4000) -> None:
        self._status.showMessage(text, timeout)
        log.debug("Status: %s", text)

    def toggle_sidebar(self) -> None:
        collapsed = self._sidebar.width() == Shell.SIDEBAR_COLLAPSED
        self._sidebar.set_collapsed(not collapsed)

    def navigate_to(self, route: str) -> None:
        widget = self._views.get(route)
        if widget is None:
            log.warning("Unknown route %s", route)
            return
        self._sidebar.set_current(route)
        self._stack.setCurrentWidget(widget)
        self.setWindowTitle(f"{__product_name__} — {title_for(route)}")
        # Close transient popovers on navigation.
        self._search_popup.hide()
        self._notif_popup.hide()
        # Refresh the destination view if it exposes refresh().
        refresh = getattr(widget, "refresh", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:  # pragma: no cover
                log.exception("View refresh failed for route %s", route)

    def replace_view(self, route: str, widget: QWidget) -> None:
        """Replace the widget registered for a route (used when late-binding
        views that depend on an authenticated principal, such as Staff & Users)."""
        existing = self._views.get(route)
        if existing is not None:
            self._stack.removeWidget(existing)
            existing.deleteLater()
        self._stack.addWidget(widget)
        self._views[route] = widget

    def on_user_activity_callbacks(self, cb) -> None:
        """Register a callback invoked on mouse/key activity (for auto-lock)."""
        self._activity.activity_detected.connect(cb)

    # ---------- slots ----------

    def _on_user_activity(self) -> None:
        # Subscribed by the app controller to reset the auto-lock timer.
        pass

    def open_patient_profile(self, patient_id: int) -> None:
        """Show the patient profile view for a given patient, building it
        lazily on first use."""
        from dentiva.ui.views.patients.profile_view import PatientProfileView
        key = "patient_profile"
        existing = self._views.get(key)
        if existing is not None:
            self._stack.removeWidget(existing)
            existing.deleteLater()
        profile = PatientProfileView(self._session_factory, self._principal, parent=self._stack)
        profile.back_requested.connect(lambda: self.navigate_to("patients"))
        self._stack.addWidget(profile)
        self._views[key] = profile
        profile.load_patient(patient_id)
        self._sidebar.set_current("patients")
        self._stack.setCurrentWidget(profile)
        self.setWindowTitle(f"{__product_name__} — Patient")

    def _on_search_result(self, route: str, entity_id: int) -> None:
        if route == "patients" and entity_id > 0:
            self.open_patient_profile(entity_id)
            return
        self.navigate_to(route)
        # If the target view supports deep-linking, pass the entity id now.
        widget = self._views.get(route)
        if widget is not None and entity_id > 0:
            selector = getattr(widget, "select_patient", None)
            if callable(selector):
                try:
                    selector(entity_id)
                except Exception:  # pragma: no cover
                    log.exception("Deep-link to %s/%s failed", route, entity_id)

    def _toggle_notifications(self) -> None:
        if self._notif_popup.isVisible():
            self._notif_popup.hide()
            return
        self._notif_popup.refresh()
        self._position_popup_on(self._notif_popup, self._header._notif_btn)
        self._notif_popup.show()
        self._notif_popup.raise_()
        self._refresh_notif_badge()

    def _position_popup_on(self, popup, anchor) -> None:
        cw = self.centralWidget()
        if cw is None or anchor is None:
            return
        bottom_right = anchor.mapTo(cw, anchor.rect().bottomRight())
        popup.adjustSize()
        x = bottom_right.x() - popup.width()
        y = bottom_right.y() + 4
        # Clamp within the central widget.
        if x < 8:
            x = 8
        popup.move(x, y)

    def _refresh_notif_badge(self) -> None:
        try:
            self._notif_popup.refresh()
            unread = self._notif_popup.unread_count
            btn = self._header._notif_btn
            btn.setText("🔔" if unread == 0 else f"🔔{unread}")
            btn.setToolTip(f"Notifications ({unread} unread)" if unread else "Notifications")
        except Exception:  # pragma: no cover
            log.exception("Notification badge refresh failed")

    def _tick_clock(self) -> None:
        self._header.refresh_datetime()

    def _confirm_logout(self) -> None:
        reply = QMessageBox.question(
            self,
            "Logout",
            "Are you sure you want to log out?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.logout_requested.emit()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.quit_requested.emit()
        event.accept()
