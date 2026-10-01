"""Navigation registry: maps route keys to view factories.

Each route is a *real working route* — no dead ends. Modules that are not
yet built (Phase 2) return a :class:`PlaceholderView`; later phases replace
the factory with the real widget.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QWidget

from dentiva.ui.widgets.placeholder import PlaceholderView

ViewFactory = Callable[[QWidget | None], QWidget]


def _placeholder(title: str, subtitle: str = "") -> ViewFactory:
    def _factory(parent: QWidget | None = None) -> QWidget:
        return PlaceholderView(title, subtitle, parent=parent)
    return _factory


ROUTES: dict[str, tuple[str, ViewFactory]] = {
    "dashboard":     ("Dashboard",      _placeholder("Dashboard", "Live tiles load after login.")),
    "patients":      ("Patients",       _placeholder("Patients", "Patient records load after login.")),
    "patient_profile": ("Patient",      _placeholder("Patient", "Patient profile loads when opened.")),
    "appointments":  ("Appointments",   _placeholder("Appointments", "Appointments & Queue load after login.")),
    "queue":         ("Queue",          _placeholder("Queue", "Reception queue for walk-ins and scheduled patients.")),
    "treatments":    ("Treatments",     _placeholder("Treatments", "Treatment catalog and patient treatment records.")),
    "prescriptions": ("Prescriptions",  _placeholder("Prescriptions", "Prescription editor and history.")),
    "invoices":      ("Invoice",        _placeholder("Invoice", "Create and manage patient invoices.")),
    "payments":      ("Payments",       _placeholder("Payments", "Payment history and transaction recording.")),
    "inventory":     ("Inventory",      _placeholder("Inventory", "Stock items, suppliers, and movements.")),
    "accounting":    ("Accounting",     _placeholder("Accounting", "Income, expenses, and financial reports.")),
    "staff":         ("Staff & Users",  _placeholder("Staff & Users", "Employees, login users, roles, and permissions.")),
    "notifications": ("Notifications",  _placeholder("Notifications", "In-app alerts and reminders.")),
    "audit":         ("Audit log",      _placeholder("Audit log", "System-wide audit trail of all significant actions.")),
    "attachments":   ("Attachments",    _placeholder("Attachments", "Files attached to patients, visits, prescriptions, invoices.")),
    "backup":        ("Backup & Restore", _placeholder("Backup & Restore", "Manual and scheduled backups; restore safety.")),
    "settings":      ("Settings",       _placeholder("Settings", "Clinic profile, dentists, printers, preferences.")),
    "about":         ("About",          _placeholder("About Dentiva Pro", "Dentiva Pro v1.0.0\nDeveloped by Shohan Khan\nhelloiamshohan@gmail.com")),
}


def view_for(route: str, parent: QWidget | None = None) -> QWidget:
    if route not in ROUTES:
        return PlaceholderView("Not found", f"No view registered for route '{route}'.", parent=parent)
    _, factory = ROUTES[route]
    return factory(parent)


def title_for(route: str) -> str:
    if route not in ROUTES:
        return "Dentiva Pro"
    return ROUTES[route][0]
