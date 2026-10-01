# mypy: disable-error-code="arg-type, attr-defined, no-any-return"
"""Font selection with Bangla (and Latin) fallbacks.

Windows typically ships "Vrinda" (Bangla) and "Segoe UI"; common open-source
Bangla fonts a clinic might install are SolaimanLipi, Kalpurush, Siyam Rupali,
Noto Sans Bengali. We ask QFontDatabase for the first available family in the
priority list so rendering works out-of-the-box on both Windows and Linux.
"""
from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase

BANGLA_FONT_CANDIDATES = (
    "SolaimanLipi",
    "Kalpurush",
    "Siyam Rupali",
    "Noto Sans Bengali",
    "Vrinda",
    "Bangla",
)

LATIN_FONT_CANDIDATES = (
    "Segoe UI",
    "Calibri",
    "Noto Sans",
    "DejaVu Sans",
    "Arial",
    "Helvetica",
)

MONO_FONT_CANDIDATES = (
    "Consolas",
    "DejaVu Sans Mono",
    "Courier New",
    "Courier",
)


def _first_existing(candidates: tuple[str, ...], fallback: str) -> str:
    families = set(QFontDatabase.families())
    for name in candidates:
        if name in families:
            return name
    return fallback


def _bangla_family() -> str:
    return _first_existing(BANGLA_FONT_CANDIDATES, "Sans Serif")


def _latin_family() -> str:
    return _first_existing(LATIN_FONT_CANDIDATES, "Sans Serif")


def _mono_family() -> str:
    return _first_existing(MONO_FONT_CANDIDATES, "Monospace")


def make_font(
    *,
    size_pt: float = 10.0,
    bold: bool = False,
    italic: bool = False,
    mono: bool = False,
) -> QFont:
    """Build a QFont that will render Bangla and Latin together.

    Strategy: pick a Latin base font, then insert the Bangla font as a fallback
    via QFont's style strategy/substitution. Qt will automatically fall back to
    the Bangla font for characters in the U+0980..U+09FF range.
    """
    fam = _mono_family() if mono else _latin_family()
    f = QFont(fam)
    f.setPointSizeF(size_pt)
    f.setBold(bold)
    f.setItalic(italic)
    # Insert Bangla family as a fallback (substitutes will be tried in order).
    bfam = _bangla_family()
    if bfam and bfam != fam:
        f.insertSubstitutions(fam, [bfam])
    return f
