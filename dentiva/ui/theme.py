"""Theme loader — substitutes design tokens into the QSS stylesheet."""
from __future__ import annotations

import re
from pathlib import Path

from dentiva.paths import paths
from dentiva.ui import design_tokens as dt

_QSS_CACHE: str | None = None


def _build_substitutions() -> dict[str, str]:
    """Map ``$TOKEN`` placeholders to concrete values from design_tokens."""
    subs: dict[str, str] = {}

    # Colors
    for name in dir(dt.Color):
        if name.startswith("_"):
            continue
        subs[name] = getattr(dt.Color, name)

    # Spacing (px)
    for name in dir(dt.Spacing):
        if name.startswith("_"):
            continue
        subs[f"S{name.lstrip('S')}"] = f"{getattr(dt.Spacing, name)}px"
    # Also add bare token names without "S" prefix? Keep to $S0..$S16 for clarity.

    # Radius
    for name in dir(dt.Radius):
        if name.startswith("_"):
            continue
        val = getattr(dt.Radius, name)
        subs[f"RADIUS_{name}"] = f"{val}px"

    # Fonts
    subs["FONT_FAMILY_UI"] = dt.Font.FAMILY_UI
    subs["FONT_FAMILY_MONO"] = dt.Font.FAMILY_MONO
    for name in dir(dt.FontSize):
        if name.startswith("_"):
            continue
        subs[f"FONT_{name}"] = f"{getattr(dt.FontSize, name)}pt"

    # Shell
    subs["HEADER_HEIGHT"] = f"{dt.Shell.HEADER_HEIGHT}px"
    # Sidebar dimensions are used in widgets via python; QSS references not needed.
    subs["CONTENT_PAD"] = f"{dt.Shell.CONTENT_PADDING}px"

    return subs


def load_stylesheet() -> str:
    global _QSS_CACHE
    if _QSS_CACHE is not None:
        return _QSS_CACHE
    qss_path = Path(paths.themes_dir) / "default.qss"
    if not qss_path.exists():
        return ""
    text = qss_path.read_text(encoding="utf-8")
    subs = _build_substitutions()
    # Replace $TOKEN (alphanumeric + _) with corresponding value; unmatched
    # tokens are left unchanged (useful for vendor extensions).
    def _repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return subs.get(key, match.group(0))

    text = re.sub(r"\$([A-Z0-9_]+)", _repl, text)
    _QSS_CACHE = text
    return text


def apply_theme(app) -> None:
    """Apply the Dentiva Pro stylesheet to a QApplication instance."""
    app.setStyle("Fusion")
    sheet = load_stylesheet()
    app.setStyleSheet(sheet)
