from decimal import Decimal

import pytest
from dentiva.core.money import format_bdt, from_paisa, parse_bdt, to_paisa


def test_to_paisa_rounds_half_up():
    assert to_paisa("1.00") == 100
    assert to_paisa("0.5") == 50
    assert to_paisa("1234.5") == 123450
    # 0.125 → ROUND_HALF_UP → 13
    assert to_paisa(Decimal("0.125")) == 13


def test_to_paisa_rejects_non_numeric():
    with pytest.raises(ValueError):
        to_paisa("abc")


def test_from_paisa_returns_decimal():
    assert from_paisa(123456) == Decimal("1234.56")
    assert from_paisa(0) == Decimal("0.00")
    assert from_paisa(-50) == Decimal("-0.50")


def test_format_bdt_uses_symbol_and_commas():
    assert format_bdt(0) == "৳0.00"
    assert format_bdt(100) == "৳1.00"
    assert format_bdt(123456) == "৳1,234.56"
    assert format_bdt(None) == "৳0.00"


def test_format_bdt_lakh_grouping():
    # 12,34,567.89
    assert format_bdt(123456789, lakh=True).replace(",", "_") == "৳12_34_567.89"


def test_parse_bdt_handles_symbol_and_commas():
    assert parse_bdt("৳1,234.56") == 123456
    assert parse_bdt("  100 ") == 10000
    assert parse_bdt("") == 0
