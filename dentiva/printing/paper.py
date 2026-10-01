"""Paper size definitions in printer's points (1 pt = 1/72 inch).

Width/height are in portrait orientation; margins are in points and are
applied symmetrically on all four sides for A4/A5; narrower for thermal rolls.
"""
from __future__ import annotations

from dataclasses import dataclass

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0


def mm_to_pt(mm: float) -> float:
    return mm / MM_PER_INCH * PT_PER_INCH


@dataclass(frozen=True)
class PaperSize:
    code: str           # "a4" | "a5" | "thermal-80" | "thermal-58"
    label: str          # Human label ("A4", "A5", "Thermal 80mm", "Thermal 58mm")
    width_pt: float     # printable page width in points (portrait)
    height_pt: float    # printable page height (0 = variable/roll for thermal)
    margin_pt: float    # uniform margin in points
    is_roll: bool = False  # True for thermal (continuous roll; height auto)


A4 = PaperSize(
    code="a4", label="A4",
    width_pt=mm_to_pt(210), height_pt=mm_to_pt(297), margin_pt=36.0,
)
A5 = PaperSize(
    code="a5", label="A5",
    width_pt=mm_to_pt(148), height_pt=mm_to_pt(210), margin_pt=28.0,
)
THERMAL_80 = PaperSize(
    code="thermal-80", label="Thermal 80mm",
    width_pt=mm_to_pt(80), height_pt=0.0, margin_pt=10.0, is_roll=True,
)
THERMAL_58 = PaperSize(
    code="thermal-58", label="Thermal 58mm",
    width_pt=mm_to_pt(58), height_pt=0.0, margin_pt=8.0, is_roll=True,
)

PAPERS: dict[str, PaperSize] = {
    p.code: p for p in (A4, A5, THERMAL_80, THERMAL_58)
}


def content_width(paper: PaperSize) -> float:
    return paper.width_pt - 2 * paper.margin_pt
