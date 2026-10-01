"""Render the Dentiva Pro application icon at all required Windows sizes.

Phase 2 produces a clean geometric placeholder icon (rounded blue square with
a stylised tooth glyph) so the application already has a valid multi-size
``.ico`` file. Later phases will refine the artwork to the finished premium
brand identity.

Usage::

    python scripts/build_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS_ICON_DIR = Path(__file__).resolve().parents[1] / "assets" / "icon"
SOURCE_SVG = ASSETS_ICON_DIR / "dentiva-pro.svg"
OUTPUT_ICO = ASSETS_ICON_DIR / "dentiva-pro.ico"

# Windows required sizes (16 through 256) plus extra HiDPI sizes.
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)

PRIMARY = (31, 90, 166, 255)       # #1F5AA6
ACCENT = (43, 165, 160, 255)      # #2BA5A0
WHITE = (255, 255, 255, 255)
TRANSPARENT = (0, 0, 0, 0)


def _render_tooth_png(size: int) -> Image.Image:
    """Draw a simple optical-centred tooth glyph on a rounded blue square."""
    img = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(img)
    pad = max(1, size // 10)
    radius = max(2, size // 6)
    draw.rounded_rectangle(
        (pad, pad, size - pad - 1, size - pad - 1),
        radius=radius,
        fill=PRIMARY,
    )

    # Tooth silhouette — simple shape for placeholder branding.
    # Coordinates are in a 100x100 box; we scale.
    s = (size - pad * 2) / 100
    ox, oy = pad, pad

    def pt(x: float, y: float) -> tuple[float, float]:
        return (ox + x * s, oy + y * s)

    # Build tooth polygon (crown + two roots).
    tooth = [
        pt(28, 18), pt(72, 18),
        pt(78, 34), pt(74, 55),
        pt(64, 62), pt(66, 78), pt(58, 88),
        pt(50, 80), pt(42, 88), pt(34, 78), pt(36, 62),
        pt(26, 55), pt(22, 34),
    ]
    draw.polygon(tooth, fill=WHITE)

    # Accent highlight
    hi = [pt(30, 22), pt(45, 22), pt(42, 30), pt(28, 30)]
    draw.polygon(hi, fill=ACCENT)

    # Downscale slightly with high-quality resampling for crisp edges.
    return img


def build_icon() -> Path:
    ASSETS_ICON_DIR.mkdir(parents=True, exist_ok=True)
    images: list[Image.Image] = []
    for sz in SIZES:
        im = _render_tooth_png(sz)
        images.append(im)
    # Save as multi-size ICO. Pillow supports the .ico container when multiple
    # sizes are appended; the largest is used as the base when appending.
    largest = images[-1]
    largest.save(
        OUTPUT_ICO,
        format="ICO",
        sizes=[(im.width, im.height) for im in images],
        append_images=images[:-1],
    )
    print(f"Wrote {OUTPUT_ICO} ({', '.join(f'{s}x{s}' for s in SIZES)})")
    return OUTPUT_ICO


if __name__ == "__main__":
    build_icon()
