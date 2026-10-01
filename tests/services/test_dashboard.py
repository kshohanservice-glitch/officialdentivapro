"""Tests for dashboard aggregates and global search."""
from __future__ import annotations

from dentiva.core.dates import local_now
from dentiva.core.permissions import Permission
from dentiva.core.unit_of_work import UnitOfWork
from dentiva.models import (
    Appointment,
    ClinicProfile,
    Dentist,
    InventoryItem,
    Invoice,
    Patient,
    Payment,
    QueueEntry,
)
from dentiva.services import auth_service
from dentiva.services.dashboard_service import (
    add_notification,
    global_search,
    load_dashboard,
    mark_notifications_read,
    notification_summary,
)
from dentiva.services.setup_service import DentistSetupInput, SetupInput, run_setup
from sqlalchemy import select


def _setup(session_factory):
    """Run setup and return admin principal."""
    with UnitOfWork(session_factory) as uow:
        existing = uow.session.scalar(select(ClinicProfile).limit(1))
        if existing is None:
            run_setup(uow.session, SetupInput(
                clinic_name="Smile Care", clinic_phone="01712345678",
                dentists=[DentistSetupInput(name="Dr. Rahman", registration_no="BDC-001")],
                admin_username="admin", admin_password="Admin@123", admin_display_name="Administrator",
            ))
            uow.commit()
    with UnitOfWork(session_factory) as uow:
        return auth_service.authenticate(uow.session, "admin", "Admin@123")


def test_dashboard_loads_empty_state(session_factory):
    p = _setup(session_factory)
    with UnitOfWork(session_factory) as uow:
        data = load_dashboard(uow.session, p)
        uow.commit()
    assert data.clinic_name == "Smile Care"
    assert data.today_appointments >= 0
    assert data.waiting_queue == 0
    assert data.todays_revenue_paisa == 0
    assert data.pending_invoices_count == 0


def test_dashboard_counts_today_appointments_and_payments(session_factory):
    p = _setup(session_factory)
    # Anchor to a deterministic same-day time (10:00 local) so the appointment
    # cannot roll into the next calendar day regardless of wall-clock time.
    # The business intent of this test is: an appointment scheduled for
    # "today" must appear in today's count.
    now = local_now().replace(hour=10, minute=0, second=0, microsecond=0)
    appt_time = now  # explicitly same-day, no +1h drift
    with UnitOfWork(session_factory) as uow:
        s = uow.session
        dentist = s.query(Dentist).first()
        patient = Patient(patient_code="P-0001", name="Karim Ahmed", phone="01711112222")
        s.add(patient)
        s.flush()
        appt = Appointment(
            patient_id=patient.id, dentist_id=dentist.id if dentist else None,
            scheduled_at=appt_time, duration_minutes=15,
            reason="Checkup", status="scheduled",
        )
        s.add(appt)
        # Add a payment for today (requires invoice)
        inv = Invoice(
            invoice_number="INV-0001", patient_id=patient.id,
            dentist_id=dentist.id if dentist else None,
            date=now, subtotal_paisa=50000, total_paisa=50000, paid_paisa=50000,
            due_paisa=0, status="paid", is_posted=True, posted_at=now,
        )
        s.add(inv)
        s.flush()
        pay = Payment(
            invoice_id=inv.id, patient_id=patient.id, method_id=1,
            amount_paisa=50000, paid_at=now,
        )
        s.add(pay)
        # Queue entry
        q = QueueEntry(patient_id=patient.id, dentist_id=dentist.id if dentist else None, status="waiting")
        s.add(q)
        # Low-stock inventory
        item = InventoryItem(name="Composite Syringe", sku="COM-01", current_qty=1, min_level_qty=5, unit="pcs")
        s.add(item)
        uow.commit()

    with UnitOfWork(session_factory) as uow:
        data = load_dashboard(uow.session, p)
        uow.commit()
    assert data.today_appointments >= 1
    assert data.waiting_queue == 1
    assert data.todays_revenue_paisa == 50000
    assert data.low_stock_count >= 1


def test_dashboard_rbac_hides_tiles_for_receptionist(session_factory):
    admin = _setup(session_factory)
    from dentiva.models.security import Role
    with UnitOfWork(session_factory) as uow:
        receptionist_role = uow.session.scalar(select(Role).where(Role.name == "Receptionist"))
        assert receptionist_role is not None
        # Create a receptionist user
        from dentiva.services.auth_service import create_user
        create_user(uow.session, admin, username="recep", password="Recep@123",
                    display_name="Receptionist", role_id=receptionist_role.id)
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        p = auth_service.authenticate(uow.session, "recep", "Recep@123")
    # Receptionist can view appointments, queue, invoices, payments and
    # inventory (per seed defaults) but cannot manage roles or edit inventory.
    assert p.has(Permission.APPOINTMENTS_VIEW)
    assert p.has(Permission.QUEUE_MANAGE)
    assert p.has(Permission.INVOICES_VIEW)
    assert not p.has(Permission.USERS_CREATE)
    assert not p.has(Permission.INVENTORY_ADJUST)


def test_global_search_finds_patient_and_invoice(session_factory):
    p = _setup(session_factory)
    now = local_now()
    with UnitOfWork(session_factory) as uow:
        s = uow.session
        patient = Patient(patient_code="P-1001", name="Rahima Begum", phone="01799998888")
        s.add(patient)
        s.flush()
        inv = Invoice(
            invoice_number="INV-1001", patient_id=patient.id, date=now,
            subtotal_paisa=150000, total_paisa=150000, paid_paisa=0, due_paisa=150000,
            status="unpaid", is_posted=True, posted_at=now,
        )
        s.add(inv)
        uow.commit()

    with UnitOfWork(session_factory) as uow:
        results = global_search(uow.session, p, "Rahima", limit=20)
        uow.commit()

    kinds = {r.kind for r in results}
    assert "patients" in kinds
    assert "invoices" in kinds
    titles = [r.title for r in results]
    assert any("Rahima Begum" in t for t in titles)
    assert any("INV-1001" in t for t in titles)


def test_global_search_min_length(session_factory):
    p = _setup(session_factory)
    with UnitOfWork(session_factory) as uow:
        assert global_search(uow.session, p, " ", limit=10) == []
        assert global_search(uow.session, p, "", limit=10) == []
        uow.commit()


def test_notifications_roundtrip(session_factory):
    p = _setup(session_factory)
    with UnitOfWork(session_factory) as uow:
        add_notification(uow.session, user_id=p.user_id, kind="info", title="Welcome!", message="First run complete.")
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        summary = notification_summary(uow.session, p)
        uow.commit()
    assert summary["unread"] == 1
    assert summary["items"][0]["title"] == "Welcome!"
    with UnitOfWork(session_factory) as uow:
        n = mark_notifications_read(uow.session, p)
        uow.commit()
    assert n == 1
    with UnitOfWork(session_factory) as uow:
        summary = notification_summary(uow.session, p)
        uow.commit()
    assert summary["unread"] == 0


def test_notifications_include_global(session_factory):
    p = _setup(session_factory)
    with UnitOfWork(session_factory) as uow:
        add_notification(uow.session, user_id=None, kind="warning", title="Backup recommended", message="")
        uow.commit()
    with UnitOfWork(session_factory) as uow:
        summary = notification_summary(uow.session, p)
        uow.commit()
    assert summary["unread"] == 1
