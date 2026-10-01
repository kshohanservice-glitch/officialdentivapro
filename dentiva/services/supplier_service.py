"""Thin alias module so imports like `from dentiva.services import supplier_service`
work uniformly alongside other services. All implementation lives in
``inventory_service`` (supplier management is part of inventory)."""
from __future__ import annotations

from dentiva.services.inventory_service import (  # noqa: F401
    SupplierInput,
    SupplierRow,
    create_supplier,
    get_supplier,
    list_suppliers,
    update_supplier,
)
