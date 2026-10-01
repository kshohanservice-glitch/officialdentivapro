"""Assemble PrescriptionDoc / InvoiceDoc from service DTOs + clinic header.

These functions are the bridge between services and the rendering layer and
have no Qt dependencies so they can be unit tested headlessly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from dentiva.printing.document import (
    ClinicHeader,
    InvoiceDoc,
    LineItemRow,
    MedicineRow,
    MoneyBlock,
    PatientBlock,
    PrescriptionDoc,
    Signature,
)
from dentiva.printing.in_words import amount_in_words_taka

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _clinic_header(session: Session) -> ClinicHeader:
    from sqlalchemy import select

    from dentiva.models import ClinicProfile
    cp = session.scalar(select(ClinicProfile).limit(1))
    if cp is None:
        return ClinicHeader()
    return ClinicHeader(
        name=cp.name or "",
        tagline=cp.tagline or "",
        address=cp.address or "",
        phone=cp.phone or "",
        email=cp.email or "",
        website=cp.website or "",
        logo_path=cp.logo_path or "",
        prescription_footer=cp.prescription_footer or "",
    )


def _patient_block(row) -> PatientBlock:
    return PatientBlock(
        name=getattr(row, "patient_name", "") or "",
        code=getattr(row, "patient_code", "") or "",
        age=str(getattr(row, "patient_age", "") or ""),
        gender=getattr(row, "patient_gender", "") or "",
        phone=getattr(row, "patient_phone", "") or "",
        address=getattr(row, "patient_address", "") or "",
    )


def _dosage_label(m) -> str:
    """Render a medicine's frequency into a short shorthand like '1+1+1'."""
    morn = 1 if m.frequency_morning else 0
    noon = 1 if m.frequency_noon else 0
    night = 1 if m.frequency_night else 0
    base = f"{morn}+{noon}+{night}"
    if m.meal_relation and m.meal_relation != "none":
        return f"{base} ({m.meal_relation} meals)"
    return base


def build_prescription_doc(
    session: Session,
    rx_row,
    *,
    paper: str = "a4",
    dentist_credentials: str = "",
    ) -> PrescriptionDoc:
    from dentiva.models import Patient
    ch = _clinic_header(session)
    patient = session.get(Patient, rx_row.patient_id) if rx_row.patient_id else None
    pb = PatientBlock()
    if patient is not None:
        pb = PatientBlock(
            name=patient.name,
            code=patient.patient_code,
            age=str(patient.age_cache) if patient.age_cache is not None else "",
            gender=patient.gender or "",
            phone=patient.phone or "",
            address=patient.address or "",
        )
    meds = [
        MedicineRow(
            name=m.name,
            form=m.form or "",
            strength=m.strength or "",
            dosage=_dosage_label(m),
            duration=f"{m.duration_days} day{'s' if m.duration_days != 1 else ''}" if m.duration_days else "",
            quantity=m.quantity or "",
            instructions=m.instructions or "",
        )
        for m in rx_row.medicines
    ]
    footer = ch.prescription_footer
    right_name = rx_row.dentist_name
    right_sub = dentist_credentials
    return PrescriptionDoc(
        paper=paper,
        clinic=ch,
        patient=pb,
        dentist_name=rx_row.dentist_name,
        dentist_credentials=right_sub,
        date=rx_row.date,
        rx_number=f"Rx #{rx_row.id}" if rx_row.id else "Rx",
        chief_complaint=rx_row.chief_complaint or "",
        on_examination=rx_row.on_examination or "",
        advice=rx_row.advice or "",
        medicines=meds,
        notes=rx_row.notes or "",
        footer=footer,
        signature=Signature(
            right_label="Doctor's signature",
            right_name=right_name,
            right_subtitle=right_sub,
        ),
    )


def build_invoice_doc(
    session: Session,
    inv_row,
    payment_rows=None,
    *,
    paper: str = "a4",
) -> InvoiceDoc:
    from dentiva.models import Patient
    patient = session.get(Patient, inv_row.patient_id) if inv_row.patient_id else None
    pb = PatientBlock()
    if patient is not None:
        pb = PatientBlock(
            name=patient.name,
            code=patient.patient_code,
            age=str(patient.age_cache) if patient.age_cache is not None else "",
            gender=patient.gender or "",
            phone=patient.phone or "",
            address=patient.address or "",
        )
    ch = _clinic_header(session)
    lines = [
        LineItemRow(
            description=li.description,
            quantity=li.quantity,
            unit_price_paisa=li.unit_price_paisa,
            line_total_paisa=li.line_total_paisa,
        )
        for li in inv_row.lines
    ]
    pay_lines = []
    if payment_rows:
        for p in payment_rows:
            if p.reversed_at is not None:
                continue
            pay_lines.append((p.method_name, p.amount_paisa, p.reference_no or ""))
    money = MoneyBlock(
        subtotal_paisa=inv_row.subtotal_paisa,
        discount_paisa=inv_row.discount_paisa,
        tax_paisa=inv_row.tax_paisa,
        total_paisa=inv_row.total_paisa,
        paid_paisa=inv_row.paid_paisa,
        due_paisa=inv_row.due_paisa,
    )
    sig = Signature(
        left_label="Received by",
        right_label="Authorised signatory",
        right_name=inv_row.dentist_name if inv_row.dentist_name and inv_row.dentist_name != "—" else "",
    )
    return InvoiceDoc(
        paper=paper,
        clinic=ch,
        patient=pb,
        invoice_number=inv_row.invoice_number,
        date=inv_row.date,
        dentist_name=inv_row.dentist_name,
        lines=lines,
        money=money,
        payment_lines=pay_lines,
        status=inv_row.status,
        notes=inv_row.notes or "",
        in_words=amount_in_words_taka(inv_row.total_paisa),
        signature=sig,
    )
