"""Vision OCR, charts and assets (WP-3, WP-6) with a fake vision client.

No network: ``FakeVision`` returns canned transcriptions, so these tests check
our pipeline (render -> OCR -> units -> chunks -> assets -> citations), not
the model's reading accuracy.
"""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

import pytest

from src.knowledge.parsing import parse_document
from src.knowledge.schemas import QueryRequest
from src.knowledge.service import KnowledgeService
from src.knowledge.vision import VisionResult, prepare_image

if TYPE_CHECKING:
    from pathlib import Path

    from src.core.config import Settings

MB = 1_048_576

RECEIPT_OCR = """ORION SYNTHETIC INDUSTRIES
EXPENSE RECEIPT
Receipt No: RCPT-55021
Date: 2026-09-14
Vendor: Harbor View Hotel
2 nights lodging USD 340.00
City tax USD 27.20
TOTAL USD 367.20"""

NOTE_OCR = """Ops meeting notes - 12 Oct
Server room door code rotates every 30 days
Next disaster recovery drill: 5 November
Facilities desk extension: 4410"""

CHART_JSON = {
    "kind": "chart",
    "chart_type": "bar",
    "title": "Quarterly Revenue 2025 (USD)",
    "x_axis": "Quarter",
    "y_axis": "Revenue (USD)",
    "series": [
        {
            "name": "Revenue",
            "points": [
                ["Q1 2025", 405000],
                ["Q2 2025", 477000],
                ["Q3 2025", 452000],
                ["Q4 2025", 510000],
            ],
        }
    ],
    "summary": "Revenue rose from 405,000 in Q1 to a peak of 510,000 in Q4 2025.",
}


class FakeVision:
    """Stands in for VisionClient; replies depend on the prompt type."""

    enabled = True
    model = "fake-vision"
    UNAVAILABLE = "fake vision disabled"

    def __init__(self, ocr_text: str = RECEIPT_OCR, fail: bool = False) -> None:
        self.ocr_text = ocr_text
        self.fail = fail
        self.calls = 0

    def describe(self, image_bytes: bytes, prompt: str) -> VisionResult:
        self.calls += 1
        if self.fail:
            return VisionResult(ok=False, model=self.model, error="TimeoutError: boom")
        text = (
            json.dumps(CHART_JSON) if prompt.startswith("Classify") else self.ocr_text
        )
        return VisionResult(
            ok=True, text=text, model=self.model, input_tokens=800, output_tokens=120
        )

    async def adescribe(self, image_bytes: bytes, prompt: str) -> VisionResult:
        return self.describe(image_bytes, prompt)


@pytest.fixture
def vision_service(
    tmp_path: Path, offline_settings: Settings, demo_dir: Path
) -> KnowledgeService:
    svc = KnowledgeService(offline_settings, data_dir=tmp_path, demo_dir=demo_dir)
    svc.vision = FakeVision()  # type: ignore[assignment]
    return svc


def test_scanned_pdf_is_ocrd_and_answerable(
    vision_service: KnowledgeService, demo_dir: Path
) -> None:
    path = demo_dir / "samples" / "scanned_receipt_no_text.pdf"
    result = vision_service.ingest(path.name, path.read_bytes())
    doc = result.document
    assert doc.chunk_count >= 1 and doc.vision_input_tokens == 800
    chunks = vision_service.store.list_chunks(doc.id)
    assert {c["source_method"] for c in chunks} == {"vision_ocr"}
    assert chunks[0]["content_type"] == "ocr" and chunks[0]["page"] == 1
    # The page render is kept so the UI can show the original.
    assert vision_service.asset_path(chunks[0]["asset_id"]) is not None

    import asyncio

    resp = asyncio.run(
        vision_service.query(
            QueryRequest(query="What was the TOTAL on receipt RCPT-55021?")
        )
    )
    cited = {c.source_id for c in resp.citations if c.valid}
    ocr_ev = [e for e in resp.evidence if e.source_method == "vision_ocr"]
    assert "367.20" in resp.answer
    assert ocr_ev and ocr_ev[0].source_id in cited and ocr_ev[0].page == 1


def test_handwritten_photo_is_accepted(
    vision_service: KnowledgeService, demo_dir: Path
) -> None:
    vision_service.vision = FakeVision(NOTE_OCR)  # type: ignore[assignment]
    path = demo_dir / "samples" / "handwritten_ops_note.jpg"
    result = vision_service.ingest(path.name, path.read_bytes())
    chunks = vision_service.store.list_chunks(result.document.id)
    assert result.document.mime_type == "image/jpeg"
    assert "disaster recovery drill" in chunks[0]["content"]
    assert chunks[0]["content_type"] == "ocr" and chunks[0]["page"] == 1


def test_chart_becomes_text_chunk_with_asset(
    vision_service: KnowledgeService, demo_dir: Path
) -> None:
    path = demo_dir / "corpus" / "FIN-RPT-011_Quarterly_Revenue_Review.pdf"
    result = vision_service.ingest(path.name, path.read_bytes())
    chunks = vision_service.store.list_chunks(result.document.id)
    charts = [c for c in chunks if c["content_type"] == "chart"]
    assert len(charts) == 1
    assert charts[0]["content"].startswith(
        "Chart: Quarterly Revenue 2025 (USD) (page 1)"
    )
    assert "| Q4 2025 | 510000 |" in charts[0]["content"]
    assert vision_service.asset_path(charts[0]["asset_id"]) is not None


def test_vision_failure_never_crashes_ingestion(
    vision_service: KnowledgeService, demo_dir: Path
) -> None:
    vision_service.vision = FakeVision(fail=True)  # type: ignore[assignment]
    path = demo_dir / "corpus" / "FIN-RPT-011_Quarterly_Revenue_Review.pdf"
    result = vision_service.ingest(path.name, path.read_bytes())
    assert result.document.chunk_count >= 1  # text layer still indexed
    assert any("Vision failed" in w for w in result.warnings)


def test_vision_call_cap_skips_pages() -> None:
    import pymupdf

    pdf = pymupdf.open()
    for _ in range(3):
        pdf.new_page()  # blank pages have no text layer -> OCR
    content = pdf.tobytes()
    fake = FakeVision()
    parsed = parse_document("scan.pdf", content, MB, vision=fake, vision_max_calls=2)
    assert fake.calls == 2 and parsed.skipped_pages == [3]
    assert any("limit reached" in w for w in parsed.warnings)


def test_images_are_downscaled_before_sending() -> None:
    from PIL import Image

    big = Image.new("RGB", (4000, 3000), (200, 30, 30))
    buf = io.BytesIO()
    big.save(buf, format="PNG")
    out = prepare_image(buf.getvalue())
    assert len(out) < 4 * MB
    with Image.open(io.BytesIO(out)) as img:
        assert max(img.size) <= 1600 and img.format == "JPEG"


def test_asset_endpoint_requires_login(client, service: KnowledgeService) -> None:
    assert client.get("/api/v1/kis/assets/nope").status_code == 404
    assert (
        client.get("/api/v1/kis/assets/nope", headers={"Authorization": ""}).status_code
        == 401
    )
