"""Printing package: paper definitions, document model, QPainter renderers, and
print/PDF/preview helpers.

Design
------
Rendering is split into two layers:

1. **Document model** (`prescription_doc`, `invoice_doc`) — pure dataclasses
   describing what to render (clinic header, patient block, line items, totals,
   signature block, footer). These are built from service-layer DTOs and know
   nothing about Qt.

2. **Renderer** (`render_document`) — takes a QPainter + a paper definition + a
   document and draws the page. All measurements are in *points* (1 pt = 1/72
   inch; standard for PDF/PostScript/Windows printing). QPrinter is configured
   with the chosen QPageSize and QPageLayout before the renderer runs.

This separation lets us unit-test document assembly without libGL, and keeps
renderers reusable across "Print", "Print preview" and "Export PDF" actions.

Paper sizes supported
---------------------
- A4  (210 × 297 mm  ≈ 595 × 842 pt)   — full prescription/invoice with letterhead
- A5  (148 × 210 mm  ≈ 420 × 595 pt)   — compact half-page chit
- Thermal 80mm  (80 × 200+ mm  ≈ 227 pt wide; long receipt)
- Thermal 58mm  (58 × 200+ mm  ≈ 165 pt wide; mini receipt)

All sizes use a 36-point (≈12.7mm) margin on each side for prescription/invoice
and a 14-point margin for thermal. Renderer uses QFont with appropriate family
fallbacks (Noto Sans Bengali / SolaimanLipi / Kalpurush / "Microsoft YaHei" /
DejaVu Sans) so Bangla text renders on both a developer's Linux machine and a
production Windows machine where the clinic may have any of the common Bangla
fonts installed.

Signature block
---------------
For prescriptions: a "Doctor's signature" line on the right with dentist name
and registration/designation below; for invoices: a "Received by" (clinic) line
on the left and "Customer signature" on the right.
"""
from __future__ import annotations
