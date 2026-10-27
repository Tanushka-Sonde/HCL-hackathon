"""Synthetic media for the demo corpus: scans, handwriting, tables and charts.

Everything here is generated locally from fictional data (Orion Synthetic
Industries); nothing is downloaded. Used by ``scripts/build_demo.py``.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from pathlib import Path

# Monthly P&L (USD). Profit = revenue - cost. Feb-Jun profit sums to 228,000.
PNL_ROWS: list[tuple[str, int, int]] = [
    ("Jan 2026", 120_000, 90_000),
    ("Feb 2026", 135_000, 98_000),
    ("Mar 2026", 150_000, 105_000),
    ("Apr 2026", 142_000, 101_000),
    ("May 2026", 160_000, 112_000),
    ("Jun 2026", 175_000, 118_000),
]

QUARTERLY_REVENUE: list[tuple[str, int]] = [
    ("Q1 2025", 405_000),
    ("Q2 2025", 477_000),
    ("Q3 2025", 452_000),
    ("Q4 2025", 510_000),
]

RECEIPT_LINES = [
    "ORION SYNTHETIC INDUSTRIES",
    "EXPENSE RECEIPT",
    "Receipt No: RCPT-55021",
    "Date: 2026-09-14",
    "Vendor: Harbor View Hotel",
    "2 nights lodging ........ USD 340.00",
    "City tax ................ USD 27.20",
    "TOTAL ................... USD 367.20",
    "Paid by corporate card. Approved: Finance desk",
]

HANDWRITTEN_LINES = [
    "Ops meeting notes - 12 Oct",
    "Server room door code rotates every 30 days",
    "Next disaster recovery drill: 5 November",
    "Facilities desk extension: 4410",
    "Owner for drill checklist: Mei Lin",
]

_HAND_FONTS = ["segoepr.ttf", "Inkfree.ttf", "LHANDW.TTF", "segoesc.ttf"]
_PLAIN_FONTS = ["arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]


def _font(candidates: list[str], size: int) -> ImageFont.ImageFont:
    for name in candidates:
        for path in (
            name,
            f"C:/Windows/Fonts/{name}",
            f"/usr/share/fonts/truetype/dejavu/{name}",
        ):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _jpeg(img: Image.Image) -> bytes:
    # JPEG keeps the generated PDFs small (PNG pages are ~1.5 MB each).
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def receipt_image() -> bytes:
    """A slightly rotated, grey 'photocopy' of a receipt (no text layer)."""
    img = Image.new("RGB", (900, 700), (236, 233, 226))
    draw = ImageDraw.Draw(img)
    font = _font(["cour.ttf", *_PLAIN_FONTS], 30)
    y = 50
    for line in RECEIPT_LINES:
        draw.text((60, y), line, fill=(40, 40, 40), font=font)
        y += 62
    return _jpeg(img.rotate(1.2, expand=True, fillcolor=(250, 250, 250)))


def handwritten_note(path: Path) -> None:
    img = Image.new("RGB", (1100, 620), (252, 249, 233))
    draw = ImageDraw.Draw(img)
    for y in range(90, 620, 70):  # ruled notebook lines
        draw.line([(40, y), (1060, y)], fill=(190, 205, 230), width=2)
    font = _font(_HAND_FONTS, 38)
    y = 40
    for i, line in enumerate(HANDWRITTEN_LINES):
        draw.text((60 + (i % 2) * 6, y), line, fill=(25, 45, 120), font=font)
        y += 70
    img.rotate(-1.5, expand=True, fillcolor=(245, 245, 245)).save(
        path, format="JPEG", quality=88
    )


def bar_chart_image() -> bytes:
    """Quarterly revenue bar chart with every value labelled."""
    w, h = 900, 560
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    title_font = _font(_PLAIN_FONTS, 30)
    font = _font(_PLAIN_FONTS, 22)
    draw.text((40, 20), "Quarterly Revenue 2025 (USD)", fill="black", font=title_font)
    left, bottom, top = 90, 480, 90
    draw.line([(left, top), (left, bottom), (w - 40, bottom)], fill="black", width=2)
    peak = max(v for _, v in QUARTERLY_REVENUE)
    slot = (w - 40 - left) / len(QUARTERLY_REVENUE)
    for i, (label, value) in enumerate(QUARTERLY_REVENUE):
        x0 = left + i * slot + slot * 0.2
        x1 = x0 + slot * 0.6
        y0 = bottom - (bottom - top - 30) * value / peak
        draw.rectangle([x0, y0, x1, bottom], fill=(37, 99, 235))
        draw.text((x0, y0 - 30), f"{value:,}", fill="black", font=font)
        draw.text((x0 + 10, bottom + 12), label, fill="black", font=font)
    return _jpeg(img)


def _text_lines(page, lines: list[str], y: float, size: float = 11) -> float:
    for line in lines:
        page.insert_text((60, y), line, fontsize=size, fontname="helv")
        y += size * 1.6
    return y


def _save(doc, path: Path) -> None:
    """Fixed metadata and no random file ID, so rebuilds are byte-identical."""
    doc.set_metadata(
        {"creationDate": "D:20260101000000", "modDate": "D:20260101000000"}
    )
    doc.save(str(path), no_new_id=True, garbage=3, deflate=True)
    doc.close()


def write_scanned_receipt_pdf(path: Path) -> None:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(40, 60, 555, 470), stream=receipt_image())
    _save(doc, path)


def write_pnl_pdf(path: Path) -> None:
    """A PDF with a ruled table that PyMuPDF's table finder can read."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = _text_lines(
        page,
        [
            "Doc-ID: FIN-RPT-010",
            "Title: Monthly Profit and Loss Report 2026",
            "Category: Finance",
            "Version: 1.0",
            "Status: effective",
            "Effective: 2026-07-01",
            "",
            "1. MONTHLY RESULTS",
            "The table below lists revenue, cost and profit for each month (USD).",
            "Profit is revenue minus cost. Figures are unaudited management accounts.",
        ],
        60,
    )
    header = ["Month", "Revenue (USD)", "Cost (USD)", "Profit (USD)"]
    rows = [header] + [[m, f"{r:,}", f"{c:,}", f"{r - c:,}"] for m, r, c in PNL_ROWS]
    col_w, row_h, x0, y0 = 118, 24, 60, y + 10
    for ri, row in enumerate(rows):
        for ci, cell in enumerate(row):
            rect = pymupdf.Rect(
                x0 + ci * col_w,
                y0 + ri * row_h,
                x0 + (ci + 1) * col_w,
                y0 + (ri + 1) * row_h,
            )
            page.draw_rect(rect, color=(0, 0, 0), width=0.8)
            page.insert_text(
                (rect.x0 + 6, rect.y0 + 16), cell, fontsize=10, fontname="helv"
            )
    _text_lines(
        page,
        ["2. NOTES", "Cost includes salaries, cloud hosting and office rent."],
        y0 + len(rows) * row_h + 40,
    )
    _save(doc, path)


def write_chart_pdf(path: Path) -> None:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = _text_lines(
        page,
        [
            "Doc-ID: FIN-RPT-011",
            "Title: Quarterly Revenue Review 2025",
            "Category: Finance",
            "Version: 1.0",
            "Status: effective",
            "Effective: 2026-01-15",
            "",
            "1. QUARTERLY REVENUE",
            "Figure 1 shows revenue for each quarter of 2025.",
            "Revenue peaked in the fourth quarter after the Orion Customer Portal launch.",
        ],
        60,
    )
    page.insert_image(
        pymupdf.Rect(60, y + 10, 535, y + 10 + 296), stream=bar_chart_image()
    )
    _save(doc, path)


COMPENSATION_DOC = """Doc-ID: HR-REC-020
Title: Employee Compensation Records (Synthetic)
Category: HR
Version: 1.0
Status: effective
Effective: 2026-04-01

1. PURPOSE
These synthetic records support payroll questions. All people and numbers are fictional.

2. RECORDS
Asha Rao (Engineering Manager, employee E-001) has an annual salary of USD 148,000, email asha.rao@orion-synthetic.example and phone +1 415-555-0142.
Tom Becker (Data Engineer, employee E-002) has an annual salary of USD 121,500, email tom.becker@orion-synthetic.example and phone +1 415-555-0178.
Mei Lin (Cloud Architect, employee E-007) has an annual salary of USD 139,000, email mei.lin@orion-synthetic.example and phone +1 415-555-0193.

3. PAYROLL CALENDAR
Salaries are paid monthly on the last working day. Bonus decisions are made in March.
"""
