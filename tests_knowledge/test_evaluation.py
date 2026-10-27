"""Evaluation runner: rank metrics, skipping, user-role cases, persistence (WP-10)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.knowledge import evaluation
from src.knowledge.evaluation import _summary, recommend, run_evaluation

if TYPE_CHECKING:
    import pytest
    from fastapi.testclient import TestClient

    from src.knowledge.service import KnowledgeService

CASES = [
    {
        "id": "t-direct",
        "scenario": "Direct factual question",
        "question": "Who must approve ACR-3310?",
        "expected_docs": ["IT-SOP-112"],
        "must_include": ["CISO"],
        "expected_behavior": "answer",
    },
    {
        "id": "t-pii",
        "scenario": "Personal data masking (user role)",
        "as_role": "user",
        "question": "What is the annual salary of Tom Becker?",
        "expected_docs": ["HR-REC-020"],
        "must_not_include": ["121,500"],
        "expected_behavior": "masked",
    },
    {
        "id": "t-llm",
        "scenario": "Table arithmetic",
        "requires": ["llm"],
        "question": "Total profit?",
        "expected_docs": [],
        "expected_behavior": "calc",
    },
]


def _row(rank, *, ok=True, answered=True, cited=True):
    return {
        "scenario": "s",
        "behavior_ok": ok,
        "retrieval_hit": rank not in (None, 0),
        "rank": rank,
        "section_match": None,
        "answer_ok": ok,
        "answered": answered,
        "grounding": 1.0,
        "citations_valid": cited,
        "judge": None,
        "outcome": "partial",
        "latency_ms": 5.0,
    }


def test_rank_metrics_and_citation_denominator() -> None:
    rows = [_row(1), _row(2), _row(0), _row(None, answered=False, cited=False)]
    summary = _summary(rows, [])
    assert summary["hit_at_1"] == round(1 / 3, 4)
    assert summary["mrr_at_5"] == round((1 + 0.5 + 0) / 3, 4)
    # The fallback case (not answered) does not count against citations.
    assert summary["citation_valid_rate"] == 1.0


def test_recommendation_logic() -> None:
    base = {k: 0.8 for k in evaluation.QUALITY_KEYS} | {"p50_latency_ms": 10}
    better = base | {"hit_at_1": 0.9}
    worse = base | {"hit_at_1": 0.7}
    assert recommend(base, better)["config"].startswith("B")
    assert recommend(base, worse)["config"].startswith("A")
    assert recommend(base, base | {"p50_latency_ms": 20})["config"].startswith("A")
    assert recommend(base, worse | {"mrr_at_5": 0.9})["config"] == "undecided"


def test_run_evaluation_skips_and_masks(
    service: KnowledgeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(evaluation, "load_eval_set", lambda: CASES)
    monkeypatch.setattr(evaluation, "write_report", lambda results: None)
    results = asyncio.run(run_evaluation(service, ["A", "B"]))
    for cfg in ("A", "B"):
        cases = {c["case_id"]: c for c in results["configs"][cfg]["cases"]}
        assert cases["t-llm"]["skipped"] == "no LLM configured"
        assert cases["t-direct"]["behavior_ok"] and cases["t-direct"]["rank"] >= 1
        assert cases["t-pii"]["behavior_ok"]  # answered as a user, so masked
        summary = results["configs"][cfg]["summary"]
        assert summary["cases"] == 2 and summary["skipped"] == 1
    assert "recommendation" in results
    assert service.store.latest_eval_run()["batch_id"] == results["batch_id"]


def test_eval_status_survives_restart(
    client: TestClient, service: KnowledgeService
) -> None:
    service.store.save_eval_run(
        "zz-last",
        "2099-01-01T00:00:00",
        "2099-01-01T00:01:00",
        {"batch_id": "zz-last", "finished_at": "2099-01-01T00:01:00", "configs": {}},
    )
    body = client.get("/api/v1/kis/eval/status").json()
    assert body["status"] == "completed" and body["result"]["batch_id"] == "zz-last"


def test_measured_retrieval_kpi(client: TestClient) -> None:
    metrics = client.get("/api/v1/kis/metrics").json()
    assert "eval_retrieval" in metrics and metrics["eval_retrieval"]["n"] >= 0


def test_config_c_is_hybrid_without_rerank(service: KnowledgeService) -> None:
    result = service.index.search(
        "Who must approve ACR-3310?",
        config_id="C",
        reranker=service.reranker,
        top_k=5,
        min_relevance=0.0,
    )
    top = result.selected[0]
    assert top.fused_rank is not None and top.rerank_score is None
    assert "no-rerank" in service.config_label("C")
