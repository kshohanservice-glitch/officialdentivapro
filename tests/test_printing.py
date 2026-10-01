"""Printing subsystem unit tests — covering the Qt-free layers: paper, in_words,
builders. QPainter/QtPrintSupport code is tested manually on Windows because
headless CI lacks a native graphics stack in this sandbox."""
from __future__ import annotations

from dentiva.printing.in_words import amount_in_words_taka
from dentiva.printing.paper import A4, A5, THERMAL_58, THERMAL_80, mm_to_pt


def test_paper_mm_to_pt():
    assert abs(mm_to_pt(210) - 595.2756) < 0.1


def test_paper_sizes_defined():
    assert A4.code == "a4"
    assert A5.code == "a5"
    assert THERMAL_80.code == "thermal-80"
    assert THERMAL_58.code == "thermal-58"
    assert A4.width_pt > A5.width_pt > THERMAL_80.width_pt > THERMAL_58.width_pt


def test_in_words_zero():
    assert amount_in_words_taka(0) == "Taka: zero only"


def test_in_words_negative_is_zero():
    assert amount_in_words_taka(-5) == "Taka: zero only"


def test_in_words_taka_only():
    assert amount_in_words_taka(100) == "Taka: one only"
    assert amount_in_words_taka(95000) == "Taka: nine hundred fifty only"


def test_in_words_with_paisa():
    assert amount_in_words_taka(105) == "Taka: one and 05/100 only"
    assert amount_in_words_taka(95050) == "Taka: nine hundred fifty and 50/100 only"


def test_in_words_only_paisa():
    assert amount_in_words_taka(1) == "Taka: 01/100 only"
    assert amount_in_words_taka(50) == "Taka: 50/100 only"
    assert amount_in_words_taka(99) == "Taka: 99/100 only"


def test_in_words_lakh_crore():
    # 1 lakh = 100,000 taka = 10,000,000 paisa
    assert "one lakh" in amount_in_words_taka(100_000 * 100)
    # 1 crore = 10,000,000 taka = 1,000,000,000 paisa
    assert "one crore" in amount_in_words_taka(10_000_000 * 100)
    # 12,34,567.89 = twelve lakh thirty-four thousand five hundred sixty-seven and 89/100
    s = amount_in_words_taka(123456789)
    assert "twelve lakh" in s
    assert "50/100" not in s
    assert "89/100" in s


def test_clinic_header_from_settings(session_factory, admin_principal):
    """build_prescription_doc pulls ClinicProfile fields including prescription_footer."""
    import datetime as dt

    from dentiva.core.unit_of_work import UnitOfWork
    from dentiva.models import ClinicProfile
    from dentiva.printing.builders import build_prescription_doc
    from dentiva.services import patient_service, prescription_service
    from sqlalchemy import select

    with UnitOfWork(session_factory) as uow:
        cp = uow.session.scalar(select(ClinicProfile).limit(1))
        if cp is None:
            cp = ClinicProfile()
            uow.session.add(cp)
        cp.name = "Smile Dental"
        cp.phone = "01700000000"
        cp.prescription_footer = "Follow up after 7 days."
        pid = patient_service.create_patient(uow.session, admin_principal, patient_service.PatientInput(
            name="Test Patient", dob=dt.date(1994, 1, 1), gender="Male", phone="01711111111"
        )).id
        rx_orm = prescription_service.create_prescription(uow.session, admin_principal,
            prescription_service.PrescriptionInput(
                patient_id=pid, chief_complaint="Toothache",
                on_examination="", advice="Warm saline rinse",
                medicines=[],
            ))
        rx_id = rx_orm.id
        uow.commit()
        rx = prescription_service.get_prescription(uow.session, admin_principal, rx_id)
        doc = build_prescription_doc(uow.session, rx, paper="a4")
        assert doc.clinic.name == "Smile Dental"
        assert doc.clinic.phone == "01700000000"
        assert doc.footer == "Follow up after 7 days."
        assert doc.patient.name == "Test Patient"


def test_build_invoice_doc_has_in_words_and_totals(session_factory, admin_principal):
    import datetime as dt

    from dentiva.core.unit_of_work import UnitOfWork
    from dentiva.printing.builders import build_invoice_doc
    from dentiva.services import invoice_service, patient_service, payment_service

    with UnitOfWork(session_factory) as uow:
        pid = patient_service.create_patient(uow.session, admin_principal, patient_service.PatientInput(
            name="Invoice Patient", dob=dt.date(1984, 1, 1), gender="Female"
        )).id
        inv = invoice_service.create_invoice(uow.session, admin_principal, invoice_service.InvoiceInput(
            patient_id=pid,
            date=None,
            discount_paisa=5000,  # 50 taka
            tax_paisa=0,
            notes="",
            lines=[
                invoice_service.InvoiceLineInput(
                    item_type="custom",
                    reference_id=None,
                    description="Consultation",
                    quantity=1,
                    unit_price_paisa=50000,
                ),
                invoice_service.InvoiceLineInput(
                    item_type="custom",
                    reference_id=None,
                    description="Scaling",
                    quantity=1,
                    unit_price_paisa=50000,
                ),
            ],
        ))
        invoice_service.post_invoice(uow.session, admin_principal, inv.id)
        inv2 = invoice_service.get_invoice(uow.session, admin_principal, inv.id)
        pays = payment_service.list_payments(uow.session, admin_principal, invoice_id=inv.id)
        doc = build_invoice_doc(uow.session, inv2, pays, paper="a4")
        uow.commit()

    assert doc.money.subtotal_paisa == 100_000
    assert doc.money.discount_paisa == 5_000
    assert doc.money.total_paisa == 95_000
    assert doc.money.due_paisa == 95_000
    assert "nine hundred fifty" in doc.in_words
    assert len(doc.lines) == 2
