"""Token budgets and accounting (WP-8)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.knowledge import generation
from src.knowledge.generation import GenerationResult, estimate_tokens, fit_to_budget
from src.knowledge.schemas import Evidence, QueryRequest
from src.knowledge.service import KnowledgeService

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from fastapi.testclient import TestClient

    from src.core.config import Settings


def _ev(sid: str, chars: int) -> Evidence:
    return Evidence(
        source_id=sid,
        chunk_id=sid,
        document_id="d",
        filename="f.txt",
        doc_id="DOC-1",
        title="T",
        content="x" * chars,
        relevance=1.0,
    )


def test_estimate_is_chars_over_four() -> None:
    assert estimate_tokens("abcd" * 10) == 10 and estimate_tokens("abcde") == 2


def test_budget_keeps_rerank_order_and_drops_the_rest() -> None:
    evidence = [_ev("S1", 2000), _ev("S2", 2000), _ev("S3", 2000)]
    fit = fit_to_budget("question?", evidence, [], [], max_input_tokens=1400)
    assert [e.source_id for e in fit.evidence] == ["S1", "S2"]
    assert fit.dropped == ["S3"] and fit.truncated is None
    assert fit.estimated_input_tokens <= 1400


def test_first_chunk_is_truncated_when_it_alone_is_too_big() -> None:
    fit = fit_to_budget("question?", [_ev("S1", 20_000)], [], [], max_input_tokens=1000)
    assert fit.truncated == "S1" and len(fit.evidence) == 1
    assert fit.evidence[0].content.endswith("[truncated to fit the input token budget]")
    assert fit.estimated_input_tokens <= 1000


def test_budget_is_recorded_and_capped(client: TestClient) -> None:
    body = client.post(
        "/api/v1/kis/query",
        json={
            "query": "What is the standard document retention period for business records?",
            "max_input_tokens": 20_000,  # above the 8,000 server cap
            "max_output_tokens": 300,
        },
    ).json()
    assert body["usage"]["budget"] == {"max_input": 8000, "max_output": 300}
    assert body["usage"]["estimated_input_tokens"] > 0
    small = client.post(
        "/api/v1/kis/query",
        json={
            "query": "What is the standard document retention period for business records?",
            "max_input_tokens": 300,
        },
    ).json()
    event = client.get(f"/api/v1/kis/queries/{small['query_id']}").json()
    trimmed = (
        event["usage"]["evidence_dropped_for_budget"]["count"]
        or event["usage"]["truncated_source"]
    )
    assert trimmed and "EVIDENCE_TRIMMED_FOR_BUDGET" in small["flags"]


def test_output_limit_is_passed_and_truncation_flagged(
    tmp_path: Path,
    offline_settings: Settings,
    demo_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = offline_settings.model_copy(update={"groq_api_key": "test-key"})
    svc = KnowledgeService(settings, data_dir=tmp_path, demo_dir=demo_dir)
    path = demo_dir / "corpus" / "IT-SOP-112_Access_Request_SOP.md"
    svc.ingest(path.name, path.read_bytes())
    seen: dict[str, int] = {}

    async def fake_llm(query, evidence, tools, turns, settings, start, max_tokens=0):
        seen["max_tokens"] = max_tokens
        return GenerationResult(
            text=f"Access request code ACR-3310 requires approval from the CISO [{evidence[0].source_id}].",
            mode="groq",
            status="ok",
            model="stub",
            input_tokens=700,
            output_tokens=64,
            finish_reason="length",
        )

    monkeypatch.setattr(generation, "_generate_groq", fake_llm)
    resp = asyncio.run(
        svc.query(
            QueryRequest(query="Who must approve ACR-3310?", max_output_tokens=64)
        )
    )
    assert seen["max_tokens"] == 64
    assert resp.outcome == "partial" and "OUTPUT_TRUNCATED" in resp.reason_codes
    assert resp.usage["input_tokens"] == 700 and resp.usage["output_tokens"] == 64
    event = svc.store.get_event(resp.query_id)
    assert event["usage"]["by_stage"]["generation"]["output_tokens"] == 64
    assert event["usage"]["estimated_cost_usd"] > 0
