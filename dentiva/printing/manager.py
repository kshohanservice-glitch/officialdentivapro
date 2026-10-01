# mypy: disable-error-code="arg-type, attr-defined, no-any-return"
"""High-level print operations: preview, print (dialog), export PDF.

All Qt GUI; import only inside QApplication process.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

from PySide6.QtCore import QMarginsF, QRectF
from PySide6.QtGui import QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog

from dentiva.printing.document import InvoiceDoc, PrescriptionDoc
from dentiva.printing.paper import A4, A5, THERMAL_58, THERMAL_80, PaperSize
from dentiva.printing.renderer import render_document

Doc = Union[PrescriptionDoc, InvoiceDoc]


def _paper_to_qpagesize(paper: PaperSize) -> QPageSize:
    if paper.code == "a4":
        return QPageSize(QPageSize.A4)
    if paper.code == "a5":
        return QPageSize(QPageSize.A5)
    # Thermal: define a custom size in mm from the paper definition.
    from PySide6.QtCore import QSizeF
    mm_w = paper.width_pt * 25.4 / 72.0
    mm_h = 200.0 if paper.is_roll else (paper.height_pt * 25.4 / 72.0)
    return QPageSize(QSizeF(mm_w, mm_h), QPageSize.Millimeter, paper.label, QPageSize.ExactMatch)


def _configure_printer(printer: QPrinter, paper: PaperSize, *, landscape: bool = False) -> None:
    qps = _paper_to_qpagesize(paper)
    printer.setPageSize(qps)
    orientation = QPageLayout.Landscape if landscape else QPageLayout.Portrait
    # Use custom margins matching our paper spec (in points). QPrinter expects
    # margins via QMarginsF in units matching QPageLayout::Point.
    m = paper.margin_pt
    printer.setPageMargins(QMarginsF(m, m, m, m), QPageLayout.Point)
    printer.setPageOrientation(orientation)
    if paper.is_roll:
        printer.setFullPage(True)


def _pagesize_to_content_rect(printer: QPrinter) -> QRectF:
    """Return the content (drawable) rectangle in points."""
    return printer.pageRect(QPrinter.Point)


def _render_pages(printer: QPrinter, doc: Doc) -> None:
    """Render document across potentially multiple pages.

    For prescriptions and invoices we keep things simple: A4/A5 assume single
    page (content fits within one page for the typical clinic use case), and
    thermal mode renders as one long page (fullPage mode with custom length
    set to content height on first pass).
    """
    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError("Failed to initialise printer.")
    try:
        rect = _pagesize_to_content_rect(printer)
        # First paint pass — if renderer returns a height taller than rect, we
        # paginate by creating new pages and shifting painter's origin.
        # We draw into a measuring painter first via the two-pass trick: for
        # simplicity we render once and then newPage if we overflow.
        # For the thermal roll we've already set a very long page; for A4/A5
        # we trust typical content fits on one page and allow overflow if it
        # doesn't (newPage for subsequent pages).
        from PySide6.QtGui import QPicture
        # Simpler approach: paint directly; if content exceeds, newPage + reposition.
        # We compute layout height by using an QPicture as a fake backend.
        pic = QPicture()
        meas = QPainter()
        meas.begin(pic)
        # Use same font DPI as printer.
        from dentiva.printing.fonts import make_font as _  # noqa: F401
        content_h = render_document(meas, QRectF(0, 0, rect.width(), 1_000_000), doc)
        meas.end()
        # Now render with possible pagination
        pages = max(1, int((content_h + rect.height() - 1) // rect.height()))
        for i in range(pages):
            if i > 0:
                printer.newPage()
            painter.save()
            painter.translate(rect.topLeft())
            # Clip and translate so renderer draws from 0,0 and page content above is hidden
            painter.setClipRect(QRectF(0, 0, rect.width(), rect.height()))
            painter.translate(0, -i * rect.height())
            # We re-run the renderer; it draws every line but only the clipped region lands on page.
            if isinstance(doc, PrescriptionDoc):
                from dentiva.printing.renderer import render_prescription
                render_prescription(painter, rect.width(), doc)
            else:
                from dentiva.printing.renderer import render_invoice
                render_invoice(painter, rect.width(), doc)
            painter.restore()
    finally:
        painter.end()


# ----- Public API

def print_document(parent, doc: Doc, *, paper_code: str = "a4") -> bool:
    """Show print dialog and print. Returns True if user accepted."""
    paper = _resolve_paper(paper_code)
    printer = QPrinter(QPrinter.HighResolution)
    _configure_printer(printer, paper)
    printer.setPrinterName("")
    dlg = QPrintDialog(printer, parent)
    dlg.setWindowTitle("Print " + ("Prescription" if isinstance(doc, PrescriptionDoc) else "Invoice"))
    if dlg.exec() != QPrintDialog.Accepted:
        return False
    _render_pages(printer, doc)
    return True


def preview_document(parent, doc: Doc, *, paper_code: str = "a4") -> None:
    """Show a print preview window."""
    paper = _resolve_paper(paper_code)
    printer = QPrinter(QPrinter.HighResolution)
    _configure_printer(printer, paper)
    dlg = QPrintPreviewDialog(printer, parent)
    dlg.setWindowTitle("Preview — " + ("Prescription" if isinstance(doc, PrescriptionDoc) else "Invoice"))
    dlg.paintRequested.connect(lambda p: _render_pages(p, doc))
    dlg.resize(900, 700)
    dlg.exec()


def export_pdf(parent, doc: Doc, default_name: str, *, paper_code: str = "a4") -> bool:
    """Prompt for PDF save path and write. Returns True on success."""
    from PySide6.QtWidgets import QFileDialog
    paper = _resolve_paper(paper_code)
    fn, _ = QFileDialog.getSaveFileName(
        parent, "Save as PDF",
        str(Path.home() / default_name),
        "PDF Files (*.pdf)",
    )
    if not fn:
        return False
    if not fn.lower().endswith(".pdf"):
        fn += ".pdf"
    printer = QPrinter(QPrinter.HighResolution)
    _configure_printer(printer, paper)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(fn)
    # Use PDF page size: for thermal, set custom length to fit content (approx 200mm).
    _render_pages(printer, doc)
    return True


def _resolve_paper(code: str) -> PaperSize:
    paper = {"a4": A4, "a5": A5, "thermal-80": THERMAL_80, "thermal-58": THERMAL_58}.get(code, A4)
    return paper
