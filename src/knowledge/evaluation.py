"""Evaluation runner and configuration experiment (brief sections 9-10).

Runs the fixed evaluation set under configuration A (vector -> LLM) and B
(hybrid -> rerank -> LLM). Every evaluation query is a normal query event
(tagged with the run ID), so results also show up in the dashboard.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger
from src.knowledge.schemas import QueryRequest, QueryResponse
from src.knowledge.service import PROJECT_ROOT, KnowledgeService

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)

EVAL_SET_PATH = PROJECT_ROOT / "demo" / "eval" / "eval_set.json"
REPORT_PATH = PROJECT_ROOT / "reports" / "evaluation_report.md"


def load_eval_set(path: Path = EVAL_SET_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _behavior_ok(case: dict[str, Any], resp: QueryResponse) -> bool:
    expected = case["expected_behavior"]
    reasons = set(resp.reason_codes)
    tools = resp.tool_calls
    answered = (
        resp.outcome != "failed"
        and "INSUFFICIENT_EVIDENCE" not in reasons
        and "INJECTION_BLOCKED" not in reasons
    )
    if expected == "answer":
        return answered
    if expected == "fallback":
        return "INSUFFICIENT_EVIDENCE" in reasons
    if expected == "conflict":
        return answered and "CONFLICT_SURFACED" in resp.flags
    if expected == "tool":
        return any(t.status == "success" for t in tools)
    if expected == "combined":
        return any(t.status == "success" for t in tools) and any(
            c.source_id.startswith("S") and c.valid for c in resp.citations
        )
    if expected == "tool_failure":
        return any(t.status == "error" for t in tools) and resp.outcome != "success"
    if expected == "injection_safe":
        forbidden = [f.lower() for f in case.get("must_not_include", [])]
        return bool(resp.safety["chunk_injections"]) and not any(
            f in resp.answer.lower() for f in forbidden
        )
    if expected == "injection_blocked":
        return "INJECTION_BLOCKED" in reasons
    return False


def _retrieval_hit(
    case: dict[str, Any], resp: QueryResponse, min_rel: float
) -> bool | None:
    expected = case.get("expected_docs") or []
    if not expected:
        return None
    found = {ev.doc_id for ev in resp.evidence if ev.relevance >= min_rel}
    return all(doc in found for doc in expected)


async def run_case(
    svc: KnowledgeService,
    case: dict[str, Any],
    config_id: str,
    run_id: str,
    pause: float,
) -> dict[str, Any]:
    session = f"{run_id}-{case['id']}"
    for prior in case.get("prior_turns", []):
        await svc.query(
            QueryRequest(query=prior, session_id=session, config_id=config_id),
            eval_meta={"run_id": run_id, "case_id": case["id"], "prior_turn": True},
        )
        await asyncio.sleep(pause)
    resp = await svc.query(
        QueryRequest(query=case["question"], session_id=session, config_id=config_id),
        eval_meta={
            "run_id": run_id,
            "case_id": case["id"],
            "scenario": case["scenario"],
        },
    )
    hit = _retrieval_hit(case, resp, svc.settings.kis_min_evidence_score)
    # Record the expected-evidence match on the stored event for the drill-down.
    event = svc.store.get_event(resp.query_id)
    if event is not None:
        event["evidence_quality"]["expected_match"] = hit
        event["eval"]["expected_docs"] = case.get("expected_docs", [])
        svc.store.update_event_payload(resp.query_id, event)
    must = [m.lower() for m in case.get("must_include", [])]
    answer_ok = all(m in resp.answer.lower() for m in must) if must else None
    await asyncio.sleep(pause)
    return {
        "case_id": case["id"],
        "scenario": case["scenario"],
        "question": case["question"],
        "query_id": resp.query_id,
        "outcome": resp.outcome,
        "reason_codes": resp.reason_codes,
        "behavior_ok": _behavior_ok(case, resp),
        "retrieval_hit": hit,
        "answer_ok": answer_ok,
        "grounding": resp.grounding_score,
        "citations_valid": bool(resp.citations)
        and all(c.valid for c in resp.citations),
        "latency_ms": resp.latency_ms,
    }


def _summary(
    rows: list[dict[str, Any]], events: list[dict[str, Any]]
) -> dict[str, Any]:
    def rate(key: str) -> float | None:
        vals = [r[key] for r in rows if r[key] is not None]
        return round(sum(1 for v in vals if v) / len(vals), 4) if vals else None

    grounding = [r["grounding"] for r in rows if r["grounding"] is not None]
    lat = [r["latency_ms"] for r in rows]
    tokens = sum(
        e["usage"]["input_tokens"] + e["usage"]["output_tokens"] for e in events
    )
    cost = sum(e["usage"]["estimated_cost_usd"] for e in events)
    return {
        "cases": len(rows),
        "behavior_pass_rate": rate("behavior_ok"),
        "retrieval_hit_rate": rate("retrieval_hit"),
        "answer_criteria_rate": rate("answer_ok"),
        "avg_grounding": round(statistics.mean(grounding), 4) if grounding else None,
        "citation_valid_rate": rate("citations_valid"),
        "success_rate": round(
            sum(1 for r in rows if r["outcome"] == "success") / len(rows), 4
        )
        if rows
        else None,
        "p50_latency_ms": round(statistics.median(lat), 2) if lat else None,
        "max_latency_ms": round(max(lat), 2) if lat else None,
        "total_tokens": tokens,
        "estimated_cost_usd": round(cost, 6),
    }


async def run_evaluation(svc: KnowledgeService, configs: list[str]) -> dict[str, Any]:
    cases = load_eval_set()
    started = datetime.now(UTC).isoformat(timespec="seconds")
    batch = uuid.uuid4().hex[:8]
    # Stay under hosted-LLM free-tier rate limits when an API key is configured.
    pause = 2.2 if svc.settings.groq_api_key else 0.0
    results: dict[str, Any] = {"started_at": started, "batch_id": batch, "configs": {}}
    for cfg in configs:
        run_id = f"eval-{batch}-{cfg}"
        rows = [await run_case(svc, case, cfg, run_id, pause) for case in cases]
        events = [
            e
            for e in svc.store.list_events()
            if (e.get("eval") or {}).get("run_id") == run_id
        ]
        results["configs"][cfg] = {
            "run_id": run_id,
            "label": svc.config_label(cfg),
            "summary": _summary(rows, events),
            "cases": rows,
        }
    results["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    results["llm"] = svc.describe()["llm_model"]
    write_report(results)
    return results


def write_report(results: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cfgs = results["configs"]
    metrics = [
        ("behavior_pass_rate", "Expected behaviour pass rate"),
        ("retrieval_hit_rate", "Retrieval hit rate (expected docs found)"),
        ("answer_criteria_rate", "Answer criteria met (must-include terms)"),
        ("avg_grounding", "Average grounding score"),
        ("citation_valid_rate", "Citations valid"),
        ("success_rate", "Outcome = Success"),
        ("p50_latency_ms", "Median latency (ms)"),
        ("max_latency_ms", "Max latency (ms)"),
        ("total_tokens", "Total LLM tokens"),
        ("estimated_cost_usd", "Estimated cost (USD)"),
    ]
    lines = [
        "# Evaluation & Configuration Comparison Report",
        "",
        f"- Run batch: `{results['batch_id']}` ({results['started_at']} -> {results['finished_at']})",
        f"- Generator: `{results['llm']}`",
        "- Evaluation set: `demo/eval/eval_set.json`",
        "",
        "## Configurations",
        "",
    ]
    for cfg, data in cfgs.items():
        lines.append(f"- **{cfg}**: `{data['label']}`")
    lines += [
        "",
        "## Summary",
        "",
        "| Metric | " + " | ".join(cfgs) + " |",
        "|---|" + "---|" * len(cfgs),
    ]
    for key, label in metrics:
        vals = [cfgs[c]["summary"][key] for c in cfgs]
        lines.append(
            f"| {label} | "
            + " | ".join("-" if v is None else str(v) for v in vals)
            + " |"
        )

    lines += ["", "## Per-case results", ""]
    header = (
        "| Case | Scenario | "
        + " | ".join(f"{c} behaviour / retrieval" for c in cfgs)
        + " |"
    )
    lines += [header, "|---|---|" + "---|" * len(cfgs)]
    first = next(iter(cfgs.values()))["cases"]
    for i, row in enumerate(first):
        cells = []
        for c in cfgs:
            r = cfgs[c]["cases"][i]
            hit = (
                "-"
                if r["retrieval_hit"] is None
                else ("hit" if r["retrieval_hit"] else "miss")
            )
            cells.append(
                f"{'pass' if r['behavior_ok'] else 'FAIL'} / {hit} ({r['outcome']})"
            )
        lines.append(
            f"| {row['case_id']} | {row['scenario']} | " + " | ".join(cells) + " |"
        )

    failures = [
        (c, r)
        for c in cfgs
        for r in cfgs[c]["cases"]
        if not r["behavior_ok"] or r["retrieval_hit"] is False
    ]
    lines += ["", "## Observed failure cases", ""]
    if failures:
        for c, r in failures:
            lines.append(
                f"- [{c}] **{r['case_id']}** ({r['scenario']}): outcome `{r['outcome']}`, "
                f"reasons {r['reason_codes']}, retrieval hit {r['retrieval_hit']} - query `{r['query_id']}`"
            )
    else:
        lines.append("- None in this run.")

    if {"A", "B"} <= set(cfgs):
        a, b = cfgs["A"]["summary"], cfgs["B"]["summary"]
        lines += ["", "## What changed and recommendation", ""]
        lines.append(
            "Configuration B adds BM25 keyword retrieval, Reciprocal Rank Fusion and a reranking "
            "stage on top of A's dense vector retrieval."
        )
        for key, label in metrics[:6]:
            if a[key] is not None and b[key] is not None:
                delta = round(b[key] - a[key], 4)
                lines.append(f"- {label}: A={a[key]} B={b[key]} (delta {delta:+})")
        lat_delta = (b["p50_latency_ms"] or 0) - (a["p50_latency_ms"] or 0)
        lines.append(f"- Median latency delta (B - A): {lat_delta:+.1f} ms")
        quality_keys = (
            "behavior_pass_rate",
            "retrieval_hit_rate",
            "answer_criteria_rate",
            "avg_grounding",
        )
        diffs = [(b[k] or 0) - (a[k] or 0) for k in quality_keys]
        if any(d > 0 for d in diffs) and not any(d < 0 for d in diffs):
            rec, why = (
                "B (hybrid + rerank)",
                "it improves quality without regressing any quality metric",
            )
        elif any(d < 0 for d in diffs) and not any(d > 0 for d in diffs):
            rec, why = "A (vector only)", "B regresses quality on this set"
        elif all(d == 0 for d in diffs):
            rec = "A (vector only)" if lat_delta > 0 else "B (hybrid + rerank)"
            why = (
                "quality is tied on this small set, so the lower-latency configuration wins; "
                "re-run on a larger corpus, where keyword/ID queries are harder for dense-only "
                "retrieval, before deciding"
            )
        else:
            rec, why = (
                "undecided",
                "the metrics move in opposite directions; inspect the failure cases",
            )
        lines.append("")
        lines.append(f"**Recommended configuration: {rec}**, because {why}.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("kis_eval_report_written", path=str(path))
