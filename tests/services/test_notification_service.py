"""Tests for notification_service — generators, settings, mark-read, dedup."""
from __future__ import annotations

import datetime as dt

import pytest
from dentiva.core.dates import TZ
from dentiva.models import (
    Appointment,
    InventoryItem,
    Invoice,
    InvoiceLineItem,
    Patient,
)
from dentiva.services import notification_service

pytestmark = pytest.mark.usefixtures("session_factory")


def _mk_patient(sess, name, code):
    p = Patient(name=name, phone="01700000000", gender="male", patient_code=code)
    sess.add(p)
    sess.flush()
    return p


def test_settings_defaults(session, admin_principal):
    assert notification_service.get_setting(session, "notif.appt_reminder.enabled", admin_principal) is True
    assert notification_service.get_setting(session, "notif.appt_reminder.lead_minutes", admin_principal) == 30
    assert notification_service.set_setting(session, "notif.appt_reminder.lead_minutes", 15, admin_principal) is True
    assert notification_service.get_setting(session, "notif.appt_reminder.lead_minutes", admin_principal) == 15


def test_settings_invalid_rejected(session, admin_principal):
    assert notification_service.set_setting(session, "notif.appt_reminder.lead_minutes", -1, admin_principal) is False
    assert notification_service.get_setting(session, "notif.appt_reminder.lead_minutes", admin_principal) == 30


def test_generate_upcoming_appointment_emits_once(session, admin_principal):
    now_local = dt.datetime.now(TZ).replace(tzinfo=None)
    patient = _mk_patient(session, "John Doe", "NT-0001")
    appt = Appointment(patient_id=patient.id, scheduled_at=now_local + dt.timedelta(minutes=10),
                       duration_minutes=15, status="scheduled", reason="Checkup")
    session.add(appt)
    session.commit()
    first = notification_service.generate_notifications(session, admin_principal)
    kinds_first = {n.kind for n in first}
    assert "appt_upcoming" in kinds_first
    session.commit()
    second = notification_service.generate_notifications(session, admin_principal)
    assert all(n.kind != "appt_upcoming" for n in second)
    session.commit()
    assert notification_service.unread_count(session, admin_principal) >= 1


def test_day_summary_first_run_of_day(session, admin_principal):
    today_local = dt.datetime.now(TZ).replace(tzinfo=None).replace(second=0, microsecond=0)
    patient = _mk_patient(session, "DaySum", "NT-0002")
    for hr in (9, 10, 11):
        a = Appointment(patient_id=patient.id,
                        scheduled_at=today_local.replace(hour=hr, minute=0),
                        duration_minutes=30, status="scheduled", reason="Cons")
        session.add(a)
    session.commit()
    notification_service.set_setting(session, "notif.today_summary.enabled", True, admin_principal)
    n1 = notification_service.generate_notifications(session, admin_principal)
    session.commit()
    assert any(n.kind == "day_summary" for n in n1)
    n2 = notification_service.generate_notifications(session, admin_principal)
    session.commit()
    assert all(n.kind != "day_summary" for n in n2)


def test_low_stock_triggers_when_enabled(session, admin_principal):
    ii = InventoryItem(name="Forceps", sku="FOR-01", unit="pcs",
                       current_qty=1, min_level_qty=5)
    session.add(ii)
    session.commit()
    notification_service.set_setting(session, "notif.low_stock.enabled", True, admin_principal)
    n1 = notification_service.generate_notifications(session, admin_principal)
    session.commit()
    assert any(n.kind == "low_stock" for n in n1)
    n2 = notification_service.generate_notifications(session, admin_principal)
    session.commit()
    assert all(n.kind != "low_stock" for n in n2)


def test_low_stock_disabled_suppresses(session, admin_principal):
    ii = InventoryItem(name="Mirror", sku="MIR-01", unit="pcs",
                       current_qty=0, min_level_qty=5)
    session.add(ii)
    session.commit()
    notification_service.set_setting(session, "notif.low_stock.enabled", False, admin_principal)
    n = notification_service.generate_notifications(session, admin_principal)
    session.commit()
    assert all(n.kind != "low_stock" for n in n)


def test_overdue_invoice_detection(session, admin_principal):
    patient = _mk_patient(session, "Late Payer", "NT-0003")
    inv = Invoice(patient_id=patient.id, invoice_number="INV-OVER",
                  is_posted=True, posted_at=dt.datetime.utcnow() - dt.timedelta(days=60),
                  total_paisa=500000, paid_paisa=0, due_paisa=500000,
                  status="unpaid", date=dt.datetime.utcnow() - dt.timedelta(days=60))
    session.add(inv)
    session.flush()
    session.add(InvoiceLineItem(
        invoice_id=inv.id, item_type="custom", description="Root canal",
        quantity=1, unit_price_paisa=500000, line_total_paisa=500000,
    ))
    session.commit()
    notification_service.set_setting(session, "notif.overdue_invoice.enabled", True, admin_principal)
    notification_service.set_setting(session, "notif.overdue_invoice.days", 7, admin_principal)
    n = notification_service.generate_notifications(session, admin_principal)
    session.commit()
    assert any(n.kind == "overdue_invoice" for n in n)


def test_mark_read_and_housekeeping(session, admin_principal):
    ii = InventoryItem(name="Prophy Paste", sku="PP-01", unit="pcs",
                       current_qty=0, min_level_qty=5)
    session.add(ii)
    session.commit()
    notification_service.set_setting(session, "notif.low_stock.enabled", True, admin_principal)
    notification_service.generate_notifications(session, admin_principal)
    session.commit()
    unread = notification_service.unread_count(session, admin_principal)
    assert unread >= 1
    m = notification_service.mark_all_read(session, admin_principal)
    session.commit()
    assert m == unread
    assert notification_service.unread_count(session, admin_principal) == 0
    from dentiva.models import Notification
    for n in session.query(Notification).all():
        n.read_at = dt.datetime.utcnow() - dt.timedelta(days=2)
    session.commit()
    notification_service.delete_all_read(session, admin_principal)
    session.commit()
    assert session.query(Notification).count() == 0


def test_list_and_filter(session, admin_principal):
    ii = InventoryItem(name="Xitem", sku="X-1", unit="pcs",
                       current_qty=0, min_level_qty=5)
    session.add(ii)
    session.commit()
    notification_service.set_setting(session, "notif.low_stock.enabled", True, admin_principal)
    notification_service.generate_notifications(session, admin_principal)
    session.commit()
    all_rows = notification_service.list_notifications(session, admin_principal, kind_filter="low_stock")
    assert all(r["kind"] == "low_stock" for r in all_rows)
    only_unread = notification_service.list_notifications(session, admin_principal, status_filter="unread")
    assert all(r["is_read"] is False for r in only_unread)
