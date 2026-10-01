"""Document models (pure dataclasses, no Qt).

These are assembled by `build_prescription_doc` / `build_invoice_doc` from service
DTOs and passed to the renderer. All strings are plain Unicode (Bangla-friendly)
and all coordinates/sizes are in points.
"""
from __future__ import annotations

import dataclasses
import datetime as dt


@dataclasses.dataclass
class ClinicHeader:
    name: str = ""
    tagline: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    logo_path: str = ""  # absolute path to a PNG/JPG; empty = no logo
    prescription_footer: str = ""


@dataclasses.dataclass
class PatientBlock:
    name: str = ""
    code: str = ""
    age: str = ""
    gender: str = ""
    phone: str = ""
    address: str = ""


@dataclasses.dataclass
class MedicineRow:
    name: str = ""
    form: str = ""
    strength: str = ""
    dosage: str = ""          # e.g. "1+0+1" or human-friendly "Morning+Night"
    duration: str = ""       # e.g. "5 days"
    quantity: str = ""
    instructions: str = ""


@dataclasses.dataclass
class LineItemRow:
    description: str = ""
    quantity: int = 1
    unit_price_paisa: int = 0
    line_total_paisa: int = 0


@dataclasses.dataclass
class MoneyBlock:
    subtotal_paisa: int = 0
    discount_paisa: int = 0
    tax_paisa: int = 0
    total_paisa: int = 0
    paid_paisa: int = 0
    due_paisa: int = 0


@dataclasses.dataclass
class Signature:
    left_label: str = ""     # e.g. "Received by"
    right_label: str = ""    # e.g. "Authorised signatory"
    right_name: str = ""     # name printed under right line
    right_subtitle: str = "" # e.g. "BDS, Reg #123"


@dataclasses.dataclass
class PrescriptionDoc:
    paper: str = "a4"
    clinic: ClinicHeader = dataclasses.field(default_factory=ClinicHeader)
    patient: PatientBlock = dataclasses.field(default_factory=PatientBlock)
    dentist_name: str = ""
    dentist_credentials: str = ""     # e.g. "BDS"
    date: dt.datetime | None = None
    rx_number: str = ""               # e.g. "Rx" or a serial
    chief_complaint: str = ""
    on_examination: str = ""
    advice: str = ""
    medicines: list[MedicineRow] = dataclasses.field(default_factory=list)
    notes: str = ""
    footer: str = ""                  # "Next visit after 7 days" / clinic tagline
    signature: Signature = dataclasses.field(default_factory=Signature)


@dataclasses.dataclass
class InvoiceDoc:
    paper: str = "a4"
    clinic: ClinicHeader = dataclasses.field(default_factory=ClinicHeader)
    patient: PatientBlock = dataclasses.field(default_factory=PatientBlock)
    invoice_number: str = ""
    date: dt.datetime | None = None
    dentist_name: str = ""
    visit_date: dt.datetime | None = None
    lines: list[LineItemRow] = dataclasses.field(default_factory=list)
    money: MoneyBlock = dataclasses.field(default_factory=MoneyBlock)
    payment_lines: list[tuple[str, int, str]] = dataclasses.field(default_factory=list)
    # (method_name, amount_paisa, reference)
    status: str = ""            # unpaid / partial / paid / void / draft
    notes: str = ""
    in_words: str = ""          # "Taka: Nine hundred fifty only"
    signature: Signature = dataclasses.field(default_factory=Signature)
