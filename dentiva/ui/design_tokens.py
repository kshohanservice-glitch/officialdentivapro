"""Design tokens: central source of truth for colors, spacing, radii, etc.

These are applied at runtime into the QSS stylesheet so we never hard-code
values across widget code.
"""
from __future__ import annotations


class Color:
    # Brand
    PRIMARY = "#1F5AA6"
    PRIMARY_HOVER = "#2A6BC0"
    PRIMARY_ACTIVE = "#174683"
    ACCENT = "#2BA5A0"

    # Neutrals
    BG_PAGE = "#F5F7FA"
    BG_SURFACE = "#FFFFFF"
    BG_SIDEBAR = "#0F2A4D"
    BG_SIDEBAR_HOVER = "#1A3B66"
    BG_SIDEBAR_ACTIVE = "#1F5AA6"
    BG_SUBTLE = "#EBEEF3"
    BG_HOVER = "#F2F4F7"
    BORDER = "#D0D5DD"
    BORDER_STRONG = "#98A2B3"
    DIVIDER = "#EAECF0"

    # Text
    TEXT_PRIMARY = "#101828"
    TEXT_SECONDARY = "#475467"
    TEXT_TERTIARY = "#667085"
    TEXT_INVERSE = "#FFFFFF"
    TEXT_MUTED = "#98A2B3"
    TEXT_LINK = "#1F5AA6"

    # Semantic
    SUCCESS = "#12B76A"
    SUCCESS_BG = "#ECFDF3"
    WARNING = "#F79009"
    WARNING_BG = "#FFFAEB"
    ERROR = "#F04438"
    ERROR_BG = "#FEF3F2"
    INFO = "#2E90FA"
    INFO_BG = "#EFF8FF"


class Spacing:
    S0 = 0
    S1 = 4
    S2 = 8
    S3 = 12
    S4 = 16
    S5 = 20
    S6 = 24
    S8 = 32
    S10 = 40
    S12 = 48
    S16 = 64


class Radius:
    SMALL = 4
    CONTROL = 6
    CARD = 8
    DIALOG = 12
    PILL = 20
    ROUND = 9999


class FontSize:
    XS = 9
    SM = 10
    MD = 11
    BASE = 12
    LG = 14
    XL = 16
    XL2 = 18
    XL3 = 24
    XL4 = 32


class Font:
    FAMILY_UI = "Segoe UI, 'Noto Sans Bengali', Vrinda, Arial, sans-serif"
    FAMILY_MONO = "Consolas, 'Courier New', monospace"


class Shell:
    HEADER_HEIGHT = 56
    SIDEBAR_EXPANDED = 240
    SIDEBAR_COLLAPSED = 64
    CONTENT_PADDING = Spacing.S6


class Shadow:
    CARD = "0 1px 2px rgba(16,24,40,0.06)"
    POPOVER = "0 4px 12px rgba(16,24,40,0.08)"
    MODAL = "0 8px 24px rgba(16,24,40,0.12)"
    NONE = "none"
