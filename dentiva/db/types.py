"""Custom SQLAlchemy column types."""
from __future__ import annotations

from typing import Any

from sqlalchemy import Integer, TypeDecorator

from dentiva.core.money import to_paisa


class Paisa(TypeDecorator):
    """Stores BDT amounts as INTEGER paisa; exposes Decimal taka in Python.

    Using an integer type eliminates any floating-point risk and is correct
    for SQLite (which does not have a dedicated money type).

    Usage::

        amount: Mapped[int] = mapped_column(Paisa, default=0)  # Python-side still int paisa for arithmetic speed.

    We keep Python-side representation as ``int`` (paisa) for performance and
    use :mod:`dentiva.core.money` helpers to format/convert. This class is
    provided for documentation/semantics and future-proofing.
    """

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        return to_paisa(value)

    def process_result_value(self, value: Any, dialect: Any) -> int | None:
        if value is None:
            return None
        return int(value)


# Re-export helper so importers can use it for type hints.
__all__ = ["Paisa"]
