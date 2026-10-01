"""ORM models. Importing this package registers all models on Base.metadata.

Import order matters to avoid circular FK references. Entities with no outgoing
FKs come first; entities that reference them follow.
"""

# Resolve forward references / late relationships now that all models are loaded.
from sqlalchemy.orm import configure_mappers

from .accounting import AccountingCategory, AccountingEntry  # noqa: F401
from .appointment import Appointment  # noqa: F401
from .attachment import Attachment  # noqa: F401
from .backup import BackupRecord  # noqa: F401
from .clinic import ClinicProfile  # noqa: F401
from .dentist import Dentist, Designation, dentist_designations  # noqa: F401
from .inventory import (  # noqa: F401
    InventoryCategory,
    InventoryItem,
    InventoryMovement,
    Supplier,
)
from .invoice import Invoice, InvoiceLineItem  # noqa: F401
from .notification import Notification  # noqa: F401
from .patient import Patient  # noqa: F401
from .payment import Payment, PaymentMethod  # noqa: F401
from .prescription import ClinicalTemplateOption, Prescription, PrescriptionMedicine  # noqa: F401
from .queue import QueueEntry  # noqa: F401
from .security import AuditEvent, PermissionAssignment, Role, User  # noqa: F401
from .settings import AppSetting, PrinterProfile  # noqa: F401
from .staff import Staff  # noqa: F401
from .treatment import TreatmentCatalog, TreatmentRecord  # noqa: F401
from .visit import DentalChartFinding, ToothReference, Visit  # noqa: F401

configure_mappers()
