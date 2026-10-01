"""Money helpers.

Dentiva Pro stores monetary amounts as **integer paisa** (1 BDT = 100 paisa) to
eliminate floating-point error. All arithmetic at the service layer uses
:class:`decimal.Decimal`; values are converted to/from paisa at the persistence
boundary.

The canonical display format is::

    ৳1,234.56     # standard
    ৳0.00         # zero
    ৳12,34,567.89 # Indian/Bangla grouping is supported when ``lakh=True``.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Union

BDT_SYMBOL = "৳"
PAISA_PER_TAKA = 100
QUANT = Decimal("0.01")  # 2-decimal quantize for BDT display

MoneyAmount = Union[int, Decimal, float, str]


def to_paisa(amount: MoneyAmount) -> int:
    """Convert a decimal/float/string taka amount to integer paisa.

    Uses ``Decimal`` and ``ROUND_HALF_UP``. Raises :class:`ValueError` on
    non-numeric or negative-context inputs.
    """
    try:
        d = Decimal(str(amount))
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"Invalid monetary amount: {amount!r}") from e
    if d < 0:
        # We allow negative amounts for reversals/refunds; caller decides validity.
        pass
    paisa = (d * PAISA_PER_TAKA).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(paisa)


def from_paisa(paisa: int) -> Decimal:
    """Convert integer paisa to Decimal taka."""
    return (Decimal(int(paisa)) / PAISA_PER_TAKA).quantize(QUANT, rounding=ROUND_HALF_UP)


def format_bdt(paisa: int | None, *, lakh: bool = False) -> str:
    """Format an integer-paisa amount for display as BDT."""
    if paisa is None:
        return f"{BDT_SYMBOL}0.00"
    taka = from_paisa(paisa)
    sign = "-" if taka < 0 else ""
    taka_str = format(abs(taka), "f")
    if "." in taka_str:
        whole, frac = taka_str.split(".", 1)
        frac = (frac + "00")[:2]
    else:
        whole, frac = taka_str, "00"
    whole = _group_digits(whole, lakh=lakh)
    return f"{sign}{BDT_SYMBOL}{whole}.{frac}"


def _group_digits(whole: str, *, lakh: bool) -> str:
    if not lakh or len(whole) <= 3:
        # Standard Western thousands separator.
        return format(int(whole), ",")
    # Indian/Bangla grouping: last 3 digits, then groups of 2.
    last3 = whole[-3:]
    head = whole[:-3]
    groups: list[str] = []
    while head:
        groups.append(head[-2:])
        head = head[:-2]
    return ",".join(reversed(groups)) + "," + last3


def parse_bdt(text: str) -> int:
    """Parse a user-entered BDT string (with/without ৳ and commas) into paisa."""
    cleaned = text.replace(BDT_SYMBOL, "").replace(",", "").strip()
    if not cleaned:
        return 0
    return to_paisa(cleaned)


def add_paisa(a: int, b: int) -> int:
    return int(a) + int(b)


def neg(amount: int) -> int:
    return -int(amount)
