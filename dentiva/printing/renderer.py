# mypy: disable-error-code="arg-type, attr-defined, no-any-return"
"""QPainter-based renderers for prescription and invoice documents.

All renderers accept a `painter` already positioned such that (0, 0) is the
top-left corner of the content area (i.e., margins have been applied by the
caller), and a `width` in points (content width) for wrapping. They return the
total height in points that was painted, so callers (thermal roll printer) can
determine the page length.

The renderers only use QPainter's primitives (drawText, drawLine, drawPixmap)
and are fully deterministic given the same document + fonts — which is what
we need for "what you preview is what prints".
"""
from __future__ import annotations

import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFontMetrics, QPainter, QPen, QPixmap

from dentiva.printing.document import InvoiceDoc, PrescriptionDoc
from dentiva.printing.fonts import make_font

AlignLeft = Qt.AlignmentFlag.AlignLeft
AlignCenter = Qt.AlignmentFlag.AlignCenter
TextWordWrap = Qt.TextFlag.TextWordWrap
BLACK = Qt.GlobalColor.black
GREY = Qt.GlobalColor.darkGray
LIGHT = Qt.GlobalColor.lightGray
THIN = 0.6
MED = 1.0
THICK = 1.6


class _Cursor:
    """Simple vertical cursor tracking y position in points."""

    __slots__ = ("y",)

    def __init__(self) -> None:
        self.y: float = 0.0

    def advance(self, pts: float) -> None:
        self.y += pts

    @property
    def here(self) -> float:
        return self.y


def _text_height(painter: QPainter, text: str, width: float) -> float:
    """Height needed to draw `text` (which may have newlines) wrapped to `width`."""
    if not text:
        return 0.0
    # Use painter.boundingRect which accepts QRectF; this is our source of truth for layout.
    rect = painter.boundingRect(QRectF(0, 0, width, 10_000), int(TextWordWrap), text)
    return rect.height()


def _draw_wrapped(
    painter: QPainter,
    x: float,
    y: float,
    width: float,
    text: str,
    *,
    align=None,
) -> float:
    """Draw text word-wrapped to width; returns the height consumed."""
    if not text:
        return 0.0
    flags = int(TextWordWrap)
    if align is not None:
        flags |= int(align)
    fm = QFontMetrics(painter.font())
    rect = QRectF(x, y, width, 10_000)
    br = painter.boundingRect(rect, flags, text)
    painter.drawText(rect, flags, text)
    return br.height()


def _hline(painter: QPainter, x: float, y: float, w: float, width: float = THIN) -> None:
    painter.save()
    pen = QPen(BLACK)
    pen.setWidthF(width)
    painter.setPen(pen)
    painter.drawLine(QPointF(x, y), QPointF(x + w, y))
    painter.restore()


def _draw_header(painter: QPainter, width: float, c: _Cursor, clinic) -> float:
    """Draw clinic letterhead. Returns the additional y advance beyond c.y.

    Layout: [logo (optional)  left 80pt] [name, tagline, address/phone/email/web]
    """
    start = c.here
    with_logo = bool(clinic.logo_path) and os.path.exists(clinic.logo_path)
    logo_w = 0.0
    logo_h = 0.0
    pix = None
    text_x = 0.0
    if with_logo:
        pix = QPixmap(clinic.logo_path)
        if not pix.isNull():
            target_h = 70.0
            logo_h = target_h
            logo_w = pix.width() * target_h / pix.height()
            if logo_w > 90.0:
                logo_w = 90.0
                logo_h = pix.height() * logo_w / pix.width()
            painter.drawPixmap(QRectF(0, c.here, logo_w, logo_h), pix, QRectF(pix.rect()))
            text_x = logo_w + 12
    # Name
    painter.setFont(make_font(size_pt=16, bold=True))
    name_h = _text_height(painter, clinic.name, width - text_x)
    _draw_wrapped(painter, text_x, c.here, width - text_x, clinic.name, align=AlignLeft)
    c.advance(name_h)
    if clinic.tagline:
        painter.setFont(make_font(size_pt=9, italic=True))
        h = _draw_wrapped(painter, text_x, c.here, width - text_x, clinic.tagline)
        c.advance(h + 2)
    # Contact block
    painter.setFont(make_font(size_pt=9))
    lines: list[str] = []
    if clinic.address:
        lines.append(clinic.address)
    contact_bits = []
    if clinic.phone:
        contact_bits.append(f"📞 {clinic.phone}")
    if clinic.email:
        contact_bits.append(f"✉ {clinic.email}")
    if clinic.website:
        contact_bits.append(clinic.website)
    if contact_bits:
        lines.append("  ·  ".join(contact_bits))
    for ln in lines:
        h = _draw_wrapped(painter, text_x, c.here, width - text_x, ln)
        c.advance(h)
    if with_logo:
        # Ensure cursor is past the logo
        if c.here < start + logo_h:
            c.y = start + logo_h
    # Separator rule
    c.advance(6)
    _hline(painter, 0, c.here, width, THICK)
    c.advance(8)
    return c.here - start


# ------------------------------------------------------------------- prescription


def render_prescription(painter: QPainter, width: float, doc: PrescriptionDoc) -> float:
    c = _Cursor()
    # Header
    _draw_header(painter, width, c, doc.clinic)

    # Title Rx
    painter.setFont(make_font(size_pt=20, bold=True))
    h = _draw_wrapped(painter, 0, c.here, width, "℞  Prescription")
    c.advance(h + 4)
    painter.setFont(make_font(size_pt=9))
    right_info = ""
    if doc.date:
        right_info = f"Date: {doc.date.strftime('%d %b %Y')}"
    if doc.rx_number:
        right_info = (doc.rx_number + ("   " + right_info if right_info else ""))
    if right_info:
        # Draw right-aligned
        fm = QFontMetrics(painter.font())
        tw = fm.horizontalAdvance(right_info)
        painter.drawText(QPointF(width - tw, c.here + fm.ascent()), right_info)
    c.advance(14)

    # Patient block
    painter.setFont(make_font(size_pt=10, bold=True))
    _draw_wrapped(painter, 0, c.here, width, "Patient")
    c.advance(_text_height(painter, "Patient", width) + 2)
    painter.setFont(make_font(size_pt=10))
    info_lines: list[str] = []
    name_line = doc.patient.name
    bits = []
    if doc.patient.age:
        bits.append(f"Age {doc.patient.age}")
    if doc.patient.gender:
        bits.append(doc.patient.gender)
    if bits:
        name_line += "  (" + ", ".join(bits) + ")"
    info_lines.append(name_line)
    if doc.patient.code:
        info_lines.append(f"ID: {doc.patient.code}")
    if doc.patient.phone:
        info_lines.append(f"Phone: {doc.patient.phone}")
    if doc.patient.address:
        info_lines.append(doc.patient.address)
    for ln in info_lines:
        h = _draw_wrapped(painter, 0, c.here, width, ln)
        c.advance(h)
    c.advance(6)

    # Clinical sections
    def _section(label: str, body: str) -> None:
        if not body:
            return
        painter.setFont(make_font(size_pt=10, bold=True))
        _draw_wrapped(painter, 0, c.here, width, label)
        c.advance(_text_height(painter, label, width) + 1)
        painter.setFont(make_font(size_pt=10))
        h = _draw_wrapped(painter, 0, c.here, width, body)
        c.advance(h + 4)

    _section("Chief complaint", doc.chief_complaint)
    _section("On examination", doc.on_examination)

    # Medicines
    if doc.medicines:
        painter.setFont(make_font(size_pt=11, bold=True))
        _draw_wrapped(painter, 0, c.here, width, "Medicines")
        c.advance(_text_height(painter, "Medicines", width) + 4)
        for idx, m in enumerate(doc.medicines, start=1):
            painter.setFont(make_font(size_pt=10, bold=True))
            head = f"{idx}. {m.name}"
            if m.strength:
                head += f"  —  {m.strength}"
            if m.form:
                head += f"  [{m.form}]"
            hh = _draw_wrapped(painter, 0, c.here, width, head)
            c.advance(hh)
            painter.setFont(make_font(size_pt=9.5))
            sub_parts = []
            if m.dosage:
                sub_parts.append(f"Dosage: {m.dosage}")
            if m.duration:
                sub_parts.append(f"Duration: {m.duration}")
            if m.quantity:
                sub_parts.append(f"Quantity: {m.quantity}")
            sub_line = "   ·   ".join(sub_parts)
            if sub_line:
                hh = _draw_wrapped(painter, 14, c.here, width - 14, sub_line)
                c.advance(hh)
            if m.instructions:
                hh = _draw_wrapped(painter, 14, c.here, width - 14, "Instructions: " + m.instructions)
                c.advance(hh)
            c.advance(3)
        c.advance(4)

    _section("Advice", doc.advice)
    _section("Notes", doc.notes)

    c.advance(14)

    # Signature block
    painter.setFont(make_font(size_pt=9))
    sig_y = c.here
    sig_w = width / 2 - 18
    # Right side signature
    right_x = width / 2 + 18
    _hline(painter, right_x, sig_y + 36, sig_w, MED)
    if doc.signature.right_name:
        painter.setFont(make_font(size_pt=10, bold=True))
        painter.drawText(QPointF(right_x, sig_y + 50), doc.signature.right_name)
        if doc.signature.right_subtitle:
            painter.setFont(make_font(size_pt=8.5))
            painter.drawText(QPointF(right_x, sig_y + 63), doc.signature.right_subtitle)
    painter.setFont(make_font(size_pt=8.5))
    painter.drawText(QPointF(right_x, sig_y + 32), doc.signature.right_label or "")

    c.y = sig_y + 70

    if doc.footer:
        c.advance(6)
        _hline(painter, 0, c.here, width, THIN)
        c.advance(4)
        painter.setFont(make_font(size_pt=8.5, italic=True))
        h = _draw_wrapped(painter, 0, c.here, width, doc.footer, align=AlignCenter)
        c.advance(h)

    return c.here


# ------------------------------------------------------------------- invoice


def render_invoice(painter: QPainter, width: float, doc: InvoiceDoc) -> float:
    c = _Cursor()
    _draw_header(painter, width, c, doc.clinic)

    # Title
    painter.setFont(make_font(size_pt=18, bold=True))
    title = "INVOICE"
    if doc.status == "draft":
        title = "INVOICE (DRAFT)"
    elif doc.status == "void":
        title = "INVOICE (VOIDED)"
    _draw_wrapped(painter, 0, c.here, width, title)
    c.advance(_text_height(painter, title, width))
    painter.setFont(make_font(size_pt=9.5))
    meta_lines = []
    meta_lines.append(f"Invoice #: {doc.invoice_number}")
    if doc.date:
        meta_lines.append(f"Date: {doc.date.strftime('%d %b %Y, %I:%M %p')}")
    if doc.status:
        meta_lines.append(f"Status: {doc.status.title()}")
    if doc.dentist_name and doc.dentist_name != "—":
        meta_lines.append(f"Provider: {doc.dentist_name}")
    for ln in meta_lines:
        _draw_wrapped(painter, 0, c.here, width, ln)
        c.advance(_text_height(painter, ln, width))
    c.advance(8)

    # Patient block
    painter.setFont(make_font(size_pt=10, bold=True))
    _draw_wrapped(painter, 0, c.here, width, "Billed to")
    c.advance(_text_height(painter, "Billed to", width) + 2)
    painter.setFont(make_font(size_pt=10))
    pname = doc.patient.name or "—"
    if doc.patient.code:
        pname += f"  [{doc.patient.code}]"
    _draw_wrapped(painter, 0, c.here, width, pname)
    c.advance(_text_height(painter, pname, width))
    sub = []
    if doc.patient.phone:
        sub.append(f"Phone: {doc.patient.phone}")
    if doc.patient.address:
        sub.append(doc.patient.address)
    for ln in sub:
        _draw_wrapped(painter, 0, c.here, width, ln)
        c.advance(_text_height(painter, ln, width))
    c.advance(8)

    # Line items table
    from dentiva.core.money import format_bdt
    col_qty = 40
    col_unit = 90
    col_line = width - col_qty - col_unit
    x_desc = 0
    x_qty = col_line
    x_unit = col_line + col_qty
    # Header row
    _hline(painter, 0, c.here, width, MED)
    c.advance(3)
    painter.setFont(make_font(size_pt=9.5, bold=True))
    painter.drawText(QPointF(x_desc, c.here + QFontMetrics(painter.font()).ascent()), "Description")
    painter.drawText(QPointF(x_qty, c.here + QFontMetrics(painter.font()).ascent()), "Qty")
    painter.drawText(QPointF(x_unit, c.here + QFontMetrics(painter.font()).ascent()), "Amount")
    c.advance(QFontMetrics(painter.font()).height() + 3)
    _hline(painter, 0, c.here, width, THIN)
    c.advance(4)
    painter.setFont(make_font(size_pt=10))
    for line in doc.lines:
        # Wrap description, compute height. Other columns share the same row height.
        desc_h = _text_height(painter, line.description, col_line - 6)
        painter.drawText(QRectF(x_desc, c.here, col_line - 6, desc_h + 4), int(TextWordWrap), line.description)
        painter.drawText(QPointF(x_qty, c.here + QFontMetrics(painter.font()).ascent()), str(line.quantity))
        amount_text = format_bdt(line.line_total_paisa)
        fm = QFontMetrics(painter.font())
        painter.drawText(QPointF(x_unit + col_unit - fm.horizontalAdvance(amount_text),
                                 c.here + fm.ascent()), amount_text)
        row_h = max(desc_h + 4, fm.height() + 4)
        c.advance(row_h)
    c.advance(2)
    _hline(painter, 0, c.here, width, MED)
    c.advance(6)

    # Totals (right-aligned block)
    label_w = width / 2
    val_x = label_w
    val_w = width - label_w

    def _total_row(label: str, amount: str, *, bold: bool = False, big: bool = False) -> None:
        painter.setFont(make_font(size_pt=11 if big else 10, bold=bold))
        fm = QFontMetrics(painter.font())
        h = fm.height() + 2
        painter.drawText(QPointF(val_x, c.here + fm.ascent()), label)
        painter.drawText(QPointF(val_x + val_w - fm.horizontalAdvance(amount), c.here + fm.ascent()), amount)
        c.advance(h)

    _total_row("Subtotal", format_bdt(doc.money.subtotal_paisa))
    if doc.money.discount_paisa:
        _total_row("Discount", "-" + format_bdt(doc.money.discount_paisa))
    if doc.money.tax_paisa:
        _total_row("Tax", format_bdt(doc.money.tax_paisa))
    _hline(painter, val_x, c.here, val_w, THIN)
    c.advance(2)
    _total_row("TOTAL", format_bdt(doc.money.total_paisa), bold=True, big=True)
    _total_row("Paid", format_bdt(doc.money.paid_paisa))
    painter.setFont(make_font(size_pt=11, bold=True))
    due_color = BLACK if doc.money.due_paisa <= 0 else Qt.GlobalColor.red
    painter.save()
    painter.setPen(due_color)
    _total_row("Balance due", format_bdt(doc.money.due_paisa), bold=True)
    painter.restore()
    c.advance(6)

    # In words
    if doc.in_words:
        painter.setFont(make_font(size_pt=9.5, italic=True))
        h = _draw_wrapped(painter, 0, c.here, width, doc.in_words)
        c.advance(h + 8)

    # Payments list
    if doc.payment_lines:
        painter.setFont(make_font(size_pt=10, bold=True))
        _draw_wrapped(painter, 0, c.here, width, "Payments received")
        c.advance(_text_height(painter, "Payments received", width) + 2)
        painter.setFont(make_font(size_pt=9.5))
        for method, amount, ref in doc.payment_lines:
            amt = format_bdt(amount)
            pay_text = f"• {method}: {amt}"
            if ref:
                pay_text += f"  (ref: {ref})"
            h = _draw_wrapped(painter, 8, c.here, width - 8, pay_text)
            c.advance(h + 1)
        c.advance(8)

    if doc.notes:
        painter.setFont(make_font(size_pt=9, italic=True))
        _draw_wrapped(painter, 0, c.here, width, "Notes: " + doc.notes)
        c.advance(_text_height(painter, "Notes: " + doc.notes, width) + 8)

    # Thank-you + signature
    painter.setFont(make_font(size_pt=9.5))
    painter.drawText(QPointF(0, c.here + QFontMetrics(painter.font()).ascent()), "Thank you for visiting!")
    c.advance(28)
    # Signature
    sig_y = c.here
    sig_w = width / 2 - 18
    if doc.signature.left_label:
        _hline(painter, 0, sig_y, sig_w, MED)
        painter.setFont(make_font(size_pt=8.5))
        painter.drawText(QPointF(0, sig_y - 4), doc.signature.left_label)
    if doc.signature.right_label:
        rx = width / 2 + 18
        _hline(painter, rx, sig_y, sig_w, MED)
        painter.setFont(make_font(size_pt=8.5))
        painter.drawText(QPointF(rx, sig_y - 4), doc.signature.right_label)
        if doc.signature.right_name:
            painter.setFont(make_font(size_pt=9, bold=True))
            painter.drawText(QPointF(rx, sig_y + 14), doc.signature.right_name)
    c.advance(24)

    return c.here


# ----- convenience: render to an arbitrary printer/PDF by setting up the painter
# and calling the right renderer per doc type.


def render_document(painter: QPainter, content_rect: QRectF, doc) -> float:
    """Dispatch to the correct renderer based on doc type.

    `content_rect` is the page content rectangle already accounting for margins.
    Painter must be started (begin) before calling this.
    """
    painter.save()
    painter.translate(content_rect.topLeft())
    if isinstance(doc, PrescriptionDoc):
        h = render_prescription(painter, content_rect.width(), doc)
    elif isinstance(doc, InvoiceDoc):
        h = render_invoice(painter, content_rect.width(), doc)
    else:
        raise TypeError(f"Unknown document type: {type(doc)!r}")
    painter.restore()
    return content_rect.top() + h
