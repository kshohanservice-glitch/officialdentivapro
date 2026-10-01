"""Tests for dental-chart FDI<->ADA mapping and finding palette constants."""
from __future__ import annotations

from dentiva.services.visit_service import (
    FINDING_CODE_TO_COLOR,
    FINDING_CODE_TO_LABEL,
    FINDINGS,
    ada_equivalent,
)


def test_adult_fdi_mapping():
    # Spot-check a few adult mappings (FDI → ADA Universal).
    assert ada_equivalent("18") == "1"   # upper right wisdom
    assert ada_equivalent("11") == "8"   # upper right central
    assert ada_equivalent("21") == "9"   # upper left central
    assert ada_equivalent("28") == "16"  # upper left wisdom
    assert ada_equivalent("38") == "17"  # lower left wisdom
    assert ada_equivalent("31") == "24"  # lower left central
    assert ada_equivalent("41") == "25"  # lower right central
    assert ada_equivalent("48") == "32"  # lower right wisdom


def test_pediatric_fdi_mapping():
    assert ada_equivalent("55") == "E"
    assert ada_equivalent("65") == "J"
    assert ada_equivalent("75") == "P"
    assert ada_equivalent("85") == "O"


def test_invalid_codes_return_empty():
    assert ada_equivalent("") == ""
    assert ada_equivalent("99") == ""
    assert ada_equivalent("ab") == ""


def test_finding_palette_complete():
    codes = {c for c, _, _ in FINDINGS}
    assert "caries" in codes
    assert "filled" in codes
    assert "healthy" in codes
    for code in codes:
        assert code in FINDING_CODE_TO_COLOR
        assert code in FINDING_CODE_TO_LABEL
