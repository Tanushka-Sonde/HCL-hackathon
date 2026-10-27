"""Build the binary demo files and the synthetic business database.

Generates (all synthetic, no external downloads):
  demo/corpus/TRV-POL-003_Travel_Expense_Policy.pdf   (multi-page PDF)
  demo/corpus/FIN-SOP-045_Procurement_SOP.docx        (DOCX with headings + table)
  demo/samples/scanned_receipt_no_text.pdf            (image-only PDF -> OCR rejection demo)
  demo/samples/corrupted_file.pdf                     (invalid PDF -> intake rejection demo)
  data/business.db                                    (SQLite from demo/business_seed.sql)

Usage:  python scripts/build_demo.py
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.knowledge.tools import build_business_db  # noqa: E402

CORPUS = ROOT / "demo" / "corpus"
SAMPLES = ROOT / "demo" / "samples"

TRAVEL_PAGES: list[list[str]] = [
    [
        "Doc-ID: TRV-POL-003",
        "Title: Travel and Expense Policy",
        "Category: Finance",
        "Version: 4.0",
        "Status: effective",
        "Effective: 2025-03-01",
        "",
        "SYNTHETIC DEMO DOCUMENT. Orion Synthetic Industries (OSI) is fictional.",
        "",
        "1 PURPOSE AND SCOPE",
        "This policy sets the rules for booking business travel and claiming travel expenses at OSI. It applies to all "
        "employees and contractors who travel on company business.",
        "",
        "2 BOOKING TRAVEL",
        "All flights and hotels must be booked through the TravelDesk portal. Economy class is required for flights "
        "shorter than 6 hours. Business class may be used for flights of 6 hours or longer, but only with prior "
        "approval from a Vice President (VP).",
        "Trips must be approved by the line manager before booking. International trips also require approval from the "
        "department head at least 14 days before departure.",
    ],
    [
        "3 PER DIEM ALLOWANCE (PDA)",
        "Travellers receive a Per Diem Allowance (PDA) to cover meals and incidental expenses. The PDA for domestic "
        "travel is USD 75 per day. The PDA for international travel is USD 120 per day.",
        "The PDA is not paid for days on which meals are provided by a conference or client.",
        "",
        "4 ACCOMMODATION",
        "The maximum hotel rate is USD 220 per night for domestic travel and USD 300 per night for international travel. "
        "Rates above the cap require written approval from the department head before booking.",
    ],
    [
        "5 EXPENSE CLAIMS",
        "Expense claims must be submitted in the ExpenseHub system within 30 days of returning from the trip. Receipts "
        "are required for every item above USD 25.",
        "Claims submitted more than 60 days after the trip require approval from the Finance Director and may be "
        "rejected.",
        "Personal expenses, fines and upgrades without approval are never reimbursed.",
    ],
]

PROCUREMENT = {
    "title": "Procurement Approval SOP",
    "meta": [
        "Doc-ID: FIN-SOP-045",
        "Title: Procurement Approval SOP",
        "Category: Finance",
        "Version: 2.2",
        "Status: effective",
        "Effective: 2025-02-01",
        "Owner: Procurement Office",
    ],
    "sections": [
        (
            "1. Purpose",
            [
                "SYNTHETIC DEMO DOCUMENT. Orion Synthetic Industries (OSI) is fictional.",
                "This SOP defines who must approve purchases of goods and services and how purchases are checked "
                "against the approved project budget.",
            ],
        ),
        (
            "2. Approval Thresholds",
            [
                "Purchases under USD 10,000 need approval from the line manager.",
                "Purchases from USD 10,000 up to USD 50,000 need approval from the department head.",
                "Purchases above USD 50,000 need CFO approval.",
                "CFO approval is also needed for any purchase that is larger than the remaining budget of the "
                "project it is charged to, whatever the purchase amount.",
            ],
        ),
        (
            "3. Quotations",
            [
                "Purchases above USD 25,000 require three written quotations from different vendors. The "
                "Procurement Office keeps the quotations for audit.",
            ],
        ),
        (
            "4. Budget Check",
            [
                "Before approving a purchase, the approver must check the remaining project budget in the "
                "project finance system. The remaining budget is the approved budget minus the amount already spent.",
            ],
        ),
    ],
    "table": [
        ("Purchase amount", "Approver"),
        ("Under USD 10,000", "Line manager"),
        ("USD 10,000 to USD 50,000", "Department head"),
        ("Above USD 50,000 or above remaining project budget", "CFO"),
    ],
}


# ── Minimal PDF writer (text only, Helvetica) ────────────────


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_text_pdf(path: Path, pages: list[list[str]], draw_only: bool = False) -> None:
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    catalog_id = add(b"")
    pages_id = add(b"")
    font_id = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    page_ids = []
    for lines in pages:
        if draw_only:
            # Vector drawing only, no text layer (stands in for a scanned page).
            ops = [
                "0.6 g",
                "60 600 475 180 re f",
                "0.2 g",
                "80 620 200 20 re f",
                "80 660 300 12 re f",
            ]
        else:
            ops = ["BT", "/F1 10.5 Tf", "14 TL", "60 790 Td"]
            for para in lines:
                wrapped = textwrap.wrap(para, 95) or [""]
                for line in wrapped:
                    ops.append(f"({_pdf_escape(line)}) Tj T*")
            ops.append("ET")
        stream = "\n".join(ops).encode("cp1252")
        content_id = add(
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        )
        page_ids.append(
            add(
                (
                    f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] "
                    f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
                ).encode()
            )
        )
    objects[catalog_id - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
    kids = " ".join(f"{p} 0 R" for p in page_ids)
    objects[pages_id - 1] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


def write_procurement_docx(path: Path) -> None:
    import docx

    document = docx.Document()
    document.add_heading(PROCUREMENT["title"], level=0)
    for line in PROCUREMENT["meta"]:
        document.add_paragraph(line)
    for heading, paragraphs in PROCUREMENT["sections"]:
        document.add_heading(heading, level=1)
        for p in paragraphs:
            document.add_paragraph(p)
    table = document.add_table(rows=0, cols=2)
    for left, right in PROCUREMENT["table"]:
        cells = table.add_row().cells
        cells[0].text = left
        cells[1].text = right
    document.save(str(path))


def main() -> None:
    CORPUS.mkdir(parents=True, exist_ok=True)
    SAMPLES.mkdir(parents=True, exist_ok=True)
    write_text_pdf(CORPUS / "TRV-POL-003_Travel_Expense_Policy.pdf", TRAVEL_PAGES)
    write_procurement_docx(CORPUS / "FIN-SOP-045_Procurement_SOP.docx")
    write_text_pdf(SAMPLES / "scanned_receipt_no_text.pdf", [[]], draw_only=True)
    (SAMPLES / "corrupted_file.pdf").write_bytes(b"this is not really a pdf file\n")
    build_business_db(
        ROOT / "data" / "business.db", ROOT / "demo" / "business_seed.sql"
    )
    print("Built demo corpus files, samples and data/business.db")


if __name__ == "__main__":
    main()
