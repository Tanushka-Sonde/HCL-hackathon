"""Tables as whole chunks and safe arithmetic in answers (WP-5)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from src.knowledge import generation
from src.knowledge.calc import CalcError, apply_calcs, safe_eval
from src.knowledge.generation import GenerationResult
from src.knowledge.parsing import parse_document, split_table
from src.knowledge.schemas import Evidence, QueryRequest
from src.knowledge.service import KnowledgeService
from src.knowledge.validation import assess_grounding

if TYPE_CHECKING:
    from pathlib import Path

    from src.core.config import Settings

MB = 1_048_576


# ── calc.py ──────────────────────────────────────────────────


def test_calc_evaluates_arithmetic() -> None:
    assert safe_eval("37,000+45,000+41,000+48,000+57,000") == 228000
    assert safe_eval("round((175000-120000)/120000*100, 1)") == 45.8
    assert safe_eval("-(3 - 5) * 2") == 4


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('echo hi')",
        "open('x')",
        "a + 1",
        "2 ** 64",
        "(1).__class__",
        "[x for x in range(9)]",
        "1 / 0",
        "lambda: 1",
    ],
)
def test_calc_rejects_unsafe_or_invalid(expr: str) -> None:
    with pytest.raises(CalcError):
        safe_eval(expr)


def test_apply_calcs_replaces_and_records() -> None:
    text, calcs = apply_calcs(
        "Total profit was {{calc: 37000+45000}} USD [S1]. Bad {{calc: x+1}}."
    )
    assert text.startswith("Total profit was 82,000 (= 37000+45000) USD [S1].")
    assert "[calculation could not be evaluated]" in text
    assert calcs[0] == {"expr": "37000+45000", "result": "82,000", "error": None}
    assert calcs[1]["result"] is None and calcs[1]["error"]


def test_grounding_accepts_calc_from_cited_operands() -> None:
    ev = Evidence(
        source_id="S1",
        chunk_id="c",
        document_id="d",
        filename="f.pdf",
        doc_id="FIN-RPT-010",
        title="Monthly Profit",
        content="| Feb 2026 | 37,000 |\n| Mar 2026 | 45,000 |",
        relevance=1.0,
    )
    answer, calcs = apply_calcs(
        "Profit for Feb and Mar 2026 was {{calc: 37,000+45,000}} [S1]."
    )
    grounded = assess_grounding(answer, [ev], [], calcs)
    assert grounded["score"] == 1.0
    # A result whose operands are not in the source is still unsupported.
    answer, calcs = apply_calcs(
        "Profit for Feb and Mar 2026 was {{calc: 37,000+99,000}} [S1]."
    )
    assert assess_grounding(answer, [ev], [], calcs)["score"] == 0.0


# ── Tables ───────────────────────────────────────────────────


def test_table_split_repeats_header() -> None:
    header = "| Month | Profit |\n| --- | --- |"
    rows = "\n".join(f"| M{i:02d} | {i * 1000} |" for i in range(60))
    pieces = split_table(f"{header}\n{rows}", max_chars=300)
    assert len(pieces) > 1
    for piece in pieces:
        assert piece.startswith(header) and len(piece) <= 300
    body = [ln for p in pieces for ln in p.splitlines()[2:]]
    assert len(body) == 60  # no row lost or duplicated


def test_pnl_table_is_one_chunk_under_its_heading(
    service: KnowledgeService, demo_dir: Path
) -> None:
    path = demo_dir / "corpus" / "FIN-RPT-010_Monthly_PnL_2026.pdf"
    parsed = parse_document(path.name, path.read_bytes(), 20 * MB)
    tables = [u for u in parsed.units if u.content_type == "table"]
    assert len(tables) == 1 and tables[0].section == "1. MONTHLY RESULTS"
    doc = next(
        d for d in service.store.list_documents() if d["doc_id"] == "FIN-RPT-010"
    )
    chunks = [
        c for c in service.store.list_chunks(doc["id"]) if c["content_type"] == "table"
    ]
    assert len(chunks) == 1
    assert chunks[0]["content"].startswith(
        "Table: 1. MONTHLY RESULTS (page 1)\n| Month |"
    )
    assert "| Jun 2026 | 175,000 | 118,000 | 57,000 |" in chunks[0]["content"]


def test_docx_table_keeps_its_section(demo_dir: Path) -> None:
    path = demo_dir / "corpus" / "FIN-SOP-045_Procurement_SOP.docx"
    parsed = parse_document(path.name, path.read_bytes(), 20 * MB)
    table = next(u for u in parsed.units if u.content_type == "table")
    assert table.text.startswith("| Purchase amount | Approver |")
    assert table.section == "4. Budget Check"  # the heading directly above it


# ── Acceptance: total profit with a (stubbed) LLM ────────────


def test_total_profit_last_five_months(
    tmp_path: Path,
    offline_settings: Settings,
    demo_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = offline_settings.model_copy(update={"groq_api_key": "test-key"})
    svc = KnowledgeService(settings, data_dir=tmp_path, demo_dir=demo_dir)
    path = demo_dir / "corpus" / "FIN-RPT-010_Monthly_PnL_2026.pdf"
    svc.ingest(path.name, path.read_bytes())

    async def fake_llm(query, evidence, tools, turns, settings, start, **kw):
        table = next(e for e in evidence if e.content_type == "table")
        return GenerationResult(
            text=(
                "Total profit for the last 5 months (Feb to Jun 2026) was "
                f"{{{{calc: 37,000+45,000+41,000+48,000+57,000}}}} USD [{table.source_id}]."
            ),
            mode="groq",
            status="ok",
            model="stub",
            input_tokens=900,
            output_tokens=40,
        )

    monkeypatch.setattr(generation, "_generate_groq", fake_llm)
    resp = asyncio.run(
        svc.query(
            QueryRequest(
                # Offline retrieval is lexical, so the question uses report words.
                query="What was the total profit (USD) of the last 5 months in the "
                "Monthly Profit and Loss Report 2026?"
            )
        )
    )
    assert "228,000" in resp.answer
    assert resp.calculations[0]["result"] == "228,000"
    assert resp.outcome == "success", resp.reason_codes
    cited = {c.source_id for c in resp.citations if c.valid}
    assert any(
        e.content_type == "table" and e.source_id in cited for e in resp.evidence
    )


def test_unformatted_calc_operands_still_ground() -> None:
    """Live gpt-oss wrote 37000+45000 while the table has 37,000 / 45,000."""
    ev = Evidence(
        source_id="S2",
        chunk_id="c",
        document_id="d",
        filename="f.pdf",
        doc_id="FIN-RPT-010",
        title="Monthly Profit and Loss Report 2026",
        content_type="table",
        content=(
            "Table: 1. MONTHLY RESULTS (page 1)\n| Month | Profit (USD) |\n| --- | --- |\n"
            "| Feb 2026 | 37,000 |\n| Mar 2026 | 45,000 |"
        ),
        relevance=1.0,
    )
    answer, calcs = apply_calcs(
        "The total profit for Feb and Mar 2026 is {{calc: 37000+45000}} USD [S2]."
    )
    assert assess_grounding(answer, [ev], [], calcs)["score"] == 1.0


def test_question_words_are_not_claims_but_new_words_are() -> None:
    ev = Evidence(
        source_id="S1",
        chunk_id="c",
        document_id="d",
        filename="f.txt",
        doc_id="D-1",
        title="T",
        content="Feb 2026 profit 37,000.",
        relevance=1.0,
    )
    restated = "The total profit of the last month was 37,000 USD [S1]."
    invented = "Profit was driven by strong sales in Europe and Asia 37,000 [S1]."
    q = "What was the total profit of the last month?"
    assert assess_grounding(restated, [ev], [], question=q)["score"] == 1.0
    assert assess_grounding(invented, [ev], [], question=q)["score"] == 0.0
