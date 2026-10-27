"""Evaluation runner and configuration experiment (brief sections 9-10).

Runs the fixed evaluation set under configuration A (vector -> LLM),
B (hybrid -> rerank -> LLM) and the ablation C (hybrid, no rerank). Every
evaluation query is a normal query event (tagged with the run ID), so
results also show up in the dashboard and can be drilled into.

Metrics:
  behaviour pass     the expected behaviour for the scenario happened
  retrieval hit      every expected document is among the selected evidence
  hit@1 / MRR@5      rank of the first expected document (1 = top)
  section match      the expected section was retrieved (when the case names one)
  answer criteria    all must-include terms appear in the answer
  citations valid    over answered cases only (fallbacks have no citations)
  LLM judge          1-5 with a reason, only when an LLM key is set
                     (model-graded, labelled as such)

Cases that need vision or an LLM are skipped, and reported as skipped, when
that capability is not configured.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger
from src.knowledge.auth import CurrentUser
from src.knowledge.schemas import QueryRequest, QueryResponse
from src.knowledge.service import PROJECT_ROOT, KnowledgeService

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)

EVAL_SET_PATH = PROJECT_ROOT / "demo" / "eval" / "eval_set.json"
REPORT_PATH = PROJECT_ROOT / "reports" / "evaluation_report.md"
# Answers to user-role cases are masked; the run uses this synthetic user.
EVAL_USER = CurrentUser("system-eval-user", "eval-user", "user")
CONFIG_NAMES = {
    "A": "vector only",
    "B": "hybrid + rerank",
    "C": "hybrid, no rerank",
}

JUDGE_PROMPT = (
    "You grade answers from an enterprise knowledge assistant. Given the "
    "question, the expected behaviour and the answer criteria, score the "
    "answer from 1 (wrong or unsafe) to 5 (correct, complete, grounded). "
    'Reply with JSON only: {"score": <1-5>, "reason": "<one sentence>"}.'
)


def load_eval_set(path: Path = EVAL_SET_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _answered(resp: QueryResponse) -> bool:
    reasons = set(resp.reason_codes)
    return (
        resp.outcome != "failed"
        and "INSUFFICIENT_EVIDENCE" not in reasons
        and "INJECTION_BLOCKED" not in reasons
    )


def _behavior_ok(case: dict[str, Any], resp: QueryResponse) -> bool:
    expected = case["expected_behavior"]
    reasons = set(resp.reason_codes)
    tools = resp.tool_calls
    answer = resp.answer.lower()
    forbidden = [f.lower() for f in case.get("must_not_include", [])]
    clean = not any(f in answer for f in forbidden)
    if expected == "answer":
        return _answered(resp) and clean
    if expected == "fallback":
        return "INSUFFICIENT_EVIDENCE" in reasons
    if expected == "conflict":
        return _answered(resp) and "CONFLICT_SURFACED" in resp.flags
    if expected == "tool":
        return any(t.status == "success" for t in tools)
    if expected == "combined":
        return any(t.status == "success" for t in tools) and any(
            c.source_id.startswith("S") and c.valid for c in resp.citations
        )
    if expected == "tool_failure":
        return any(t.status == "error" for t in tools) and resp.outcome != "success"
    if expected == "injection_safe":
        return bool(resp.safety["chunk_injections"]) and clean
    if expected == "injection_blocked":
        return "INJECTION_BLOCKED" in reasons
    if expected == "chart":
        return any(v["kind"] == "generated_chart" for v in resp.visuals)
    if expected == "masked":
        return "PII_MASKED" in resp.flags and clean
    if expected == "calc":
        return bool(resp.calculations) and _answered(resp)
    return False


def _rank(case: dict[str, Any], resp: QueryResponse, min_rel: float) -> int | None:
    """1-based rank of the first expected document among selected evidence."""
    expected = set(case.get("expected_docs") or [])
    if not expected:
        return None
    for i, ev in enumerate(resp.evidence, start=1):
        if ev.doc_id in expected and ev.relevance >= min_rel:
            return i
    return 0  # expected but not retrieved


def _retrieval_hit(
    case: dict[str, Any], resp: QueryResponse, min_rel: float
) -> bool | None:
    expected = case.get("expected_docs") or []
    if not expected:
        return None
    found = {ev.doc_id for ev in resp.evidence if ev.relevance >= min_rel}
    return all(doc in found for doc in expected)


def _section_match(case: dict[str, Any], resp: QueryResponse) -> bool | None:
    want = (case.get("expected_section") or "").lower()
    if not want:
        return None
    return any(want in (ev.section or "").lower() for ev in resp.evidence)


def _missing_capability(svc: KnowledgeService, case: dict[str, Any]) -> str | None:
    for need in case.get("requires", []):
        if need == "vision" and not svc.vision.enabled:
            return "vision not configured"
        if need == "llm" and not svc.settings.groq_api_key:
            return "no LLM configured"
    return None


async def _judge(
    svc: KnowledgeService, case: dict[str, Any], answer: str
) -> dict[str, Any] | None:
    if not svc.settings.groq_api_key:
        return None
    from src.knowledge.generation import get_async_client, model_options
    from src.knowledge.vision import parse_json_reply

    criteria = {
        "expected_behavior": case["expected_behavior"],
        "must_include": case.get("must_include", []),
        "must_not_include": case.get("must_not_include", []),
    }
    try:
        completion = await get_async_client(svc.settings).chat.completions.create(
            model=svc.settings.groq_model_name,
            messages=[
                {"role": "system", "content": JUDGE_PROMPT},
                {
                    "role": "user",
                    "content": f"Question: {case['question']}\n"
                    f"Criteria: {json.dumps(criteria)}\nAnswer: {answer}",
                },
            ],
            temperature=0.0,
            max_tokens=300,
            **model_options(svc.settings),
        )
        data = parse_json_reply(completion.choices[0].message.content or "") or {}
        score = int(data.get("score", 0))
        if 1 <= score <= 5:
            return {"score": score, "reason": str(data.get("reason", ""))[:300]}
    except Exception as exc:
        logger.warning("kis_eval_judge_failed", error=str(exc)[:200])
    return None


async def run_case(
    svc: KnowledgeService,
    case: dict[str, Any],
    config_id: str,
    run_id: str,
    pause: float,
) -> dict[str, Any]:
    skipped = _missing_capability(svc, case)
    if skipped:
        return {
            "case_id": case["id"],
            "scenario": case["scenario"],
            "question": case["question"],
            "skipped": skipped,
        }
    if case.get("ingest_sample"):
        sample = PROJECT_ROOT / case["ingest_sample"]
        await asyncio.to_thread(svc.ingest, sample.name, sample.read_bytes())

    user = EVAL_USER if case.get("as_role") == "user" else None
    session = f"{run_id}-{case['id']}"
    for prior in case.get("prior_turns", []):
        await svc.query(
            QueryRequest(query=prior, session_id=session, config_id=config_id),
            eval_meta={"run_id": run_id, "case_id": case["id"], "prior_turn": True},
            user=user,
        )
        await asyncio.sleep(pause)
    resp = await svc.query(
        QueryRequest(query=case["question"], session_id=session, config_id=config_id),
        eval_meta={
            "run_id": run_id,
            "case_id": case["id"],
            "scenario": case["scenario"],
        },
        user=user,
    )
    min_rel = svc.settings.kis_min_evidence_score
    hit = _retrieval_hit(case, resp, min_rel)
    rank = _rank(case, resp, min_rel)
    must = [m.lower() for m in case.get("must_include", [])]
    answer_ok = all(m in resp.answer.lower() for m in must) if must else None
    judge = await _judge(svc, case, resp.answer)
    # Record the expected-evidence match on the stored event for the drill-down
    # and the dashboard's measured-retrieval KPI.
    event = svc.store.get_event(resp.query_id)
    if event is not None:
        event["evidence_quality"]["expected_match"] = hit
        event["eval"].update(
            expected_docs=case.get("expected_docs", []), rank=rank, judge=judge
        )
        svc.store.update_event_payload(resp.query_id, event)
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
        "rank": rank,
        "section_match": _section_match(case, resp),
        "answer_ok": answer_ok,
        "answered": _answered(resp),
        "grounding": resp.grounding_score,
        "citations_valid": bool(resp.citations)
        and all(c.valid for c in resp.citations),
        "judge": judge,
        "latency_ms": resp.latency_ms,
    }


def _summary(
    rows: list[dict[str, Any]], events: list[dict[str, Any]]
) -> dict[str, Any]:
    ran = [r for r in rows if not r.get("skipped")]

    def rate(key: str, subset: list[dict[str, Any]] | None = None) -> float | None:
        vals = [
            r[key]
            for r in (subset if subset is not None else ran)
            if r[key] is not None
        ]
        return round(sum(1 for v in vals if v) / len(vals), 4) if vals else None

    ranks = [r["rank"] for r in ran if r["rank"] is not None]
    grounding = [r["grounding"] for r in ran if r["grounding"] is not None]
    judged = [r["judge"]["score"] for r in ran if r.get("judge")]
    lat = [r["latency_ms"] for r in ran]
    tokens = sum(
        e["usage"]["input_tokens"] + e["usage"]["output_tokens"] for e in events
    )
    cost = sum(e["usage"]["estimated_cost_usd"] for e in events)
    by_scenario: dict[str, dict[str, int]] = defaultdict(
        lambda: {"cases": 0, "passed": 0}
    )
    for r in ran:
        by_scenario[r["scenario"]]["cases"] += 1
        by_scenario[r["scenario"]]["passed"] += int(r["behavior_ok"])
    return {
        "cases": len(ran),
        "skipped": len(rows) - len(ran),
        "behavior_pass_rate": rate("behavior_ok"),
        "retrieval_hit_rate": rate("retrieval_hit"),
        "hit_at_1": round(sum(1 for k in ranks if k == 1) / len(ranks), 4)
        if ranks
        else None,
        "mrr_at_5": round(
            statistics.mean(1 / k if 0 < k <= 5 else 0.0 for k in ranks), 4
        )
        if ranks
        else None,
        "section_match_rate": rate("section_match"),
        "answer_criteria_rate": rate("answer_ok"),
        "avg_grounding": round(statistics.mean(grounding), 4) if grounding else None,
        # Same denominator as the dashboard: answered cases only.
        "citation_valid_rate": rate(
            "citations_valid", [r for r in ran if r["answered"]]
        ),
        "judge_avg": round(statistics.mean(judged), 2) if judged else None,
        "success_rate": round(
            sum(1 for r in ran if r["outcome"] == "success") / len(ran), 4
        )
        if ran
        else None,
        "p50_latency_ms": round(statistics.median(lat), 2) if lat else None,
        "max_latency_ms": round(max(lat), 2) if lat else None,
        "total_tokens": tokens,
        "estimated_cost_usd": round(cost, 6),
        "by_scenario": dict(by_scenario),
    }


QUALITY_KEYS = (
    "behavior_pass_rate",
    "retrieval_hit_rate",
    "hit_at_1",
    "mrr_at_5",
    "answer_criteria_rate",
    "avg_grounding",
)


def recommend(a: dict[str, Any], b: dict[str, Any]) -> dict[str, str]:
    """Compare B with A on quality first, then latency."""
    diffs = [(b[k] or 0) - (a[k] or 0) for k in QUALITY_KEYS]
    lat_delta = (b["p50_latency_ms"] or 0) - (a["p50_latency_ms"] or 0)
    if any(d > 0 for d in diffs) and not any(d < 0 for d in diffs):
        return {
            "config": "B (hybrid + rerank)",
            "why": "it improves quality without regressing any quality metric.",
        }
    if any(d < 0 for d in diffs) and not any(d > 0 for d in diffs):
        return {"config": "A (vector only)", "why": "B regresses quality on this set."}
    if all(d == 0 for d in diffs):
        cfg = "A (vector only)" if lat_delta > 0 else "B (hybrid + rerank)"
        return {
            "config": cfg,
            "why": "quality is tied on this set, so the lower-latency configuration wins. "
            "Re-run with semantic embeddings and an LLM before deciding.",
        }
    return {
        "config": "undecided",
        "why": "the metrics move in opposite directions; inspect the failure cases.",
    }


async def run_evaluation(svc: KnowledgeService, configs: list[str]) -> dict[str, Any]:
    cases = load_eval_set()
    started = datetime.now(UTC).isoformat(timespec="seconds")
    batch = uuid.uuid4().hex[:8]
    # Stay under hosted-LLM free-tier rate limits when an API key is configured.
    pause = 2.2 if svc.settings.groq_api_key else 0.0
    results: dict[str, Any] = {
        "started_at": started,
        "batch_id": batch,
        "case_count": len(cases),
        "configs": {},
    }
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
    results["embedder"] = svc.embedder_name
    results["reranker"] = svc.reranker.name
    if {"A", "B"} <= set(results["configs"]):
        results["recommendation"] = recommend(
            results["configs"]["A"]["summary"], results["configs"]["B"]["summary"]
        )
    svc.store.save_eval_run(batch, started, results["finished_at"], results)
    write_report(results)
    return results


def write_report(results: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cfgs = results["configs"]
    metrics = [
        ("behavior_pass_rate", "Expected behaviour pass rate"),
        ("retrieval_hit_rate", "Retrieval hit rate (expected docs found)"),
        ("hit_at_1", "Hit@1 (expected doc ranked first)"),
        ("mrr_at_5", "MRR@5"),
        ("section_match_rate", "Expected section retrieved"),
        ("answer_criteria_rate", "Answer criteria met (must-include terms)"),
        ("avg_grounding", "Average grounding score"),
        ("citation_valid_rate", "Citations valid (answered cases only)"),
        ("judge_avg", "LLM judge, 1-5 (model-graded)"),
        ("success_rate", "Outcome = Success"),
        ("p50_latency_ms", "Median latency (ms)"),
        ("max_latency_ms", "Max latency (ms)"),
        ("total_tokens", "Total LLM tokens"),
        ("estimated_cost_usd", "Estimated cost (USD)"),
    ]
    first = next(iter(cfgs.values()))
    lines = [
        "# Evaluation & Configuration Comparison Report",
        "",
        f"- Run batch: `{results['batch_id']}` ({results['started_at']} -> {results['finished_at']})",
        f"- Generator: `{results['llm']}` · embedder `{results.get('embedder')}` · reranker `{results.get('reranker')}`",
        f"- Evaluation set: `demo/eval/eval_set.json` ({results.get('case_count')} cases; "
        f"{first['summary']['skipped']} skipped because a capability is not configured)",
        "",
        "## Configurations",
        "",
    ]
    for cfg, data in cfgs.items():
        lines.append(f"- **{cfg}** ({CONFIG_NAMES.get(cfg, cfg)}): `{data['label']}`")
    lines += [
        "",
        "## Summary",
        "",
        "| Metric | " + " | ".join(cfgs) + " |",
        "|---|" + "---|" * len(cfgs),
    ]
    for key, label in metrics:
        vals = [cfgs[c]["summary"].get(key) for c in cfgs]
        if all(v is None for v in vals):
            continue
        lines.append(
            f"| {label} | "
            + " | ".join("-" if v is None else str(v) for v in vals)
            + " |"
        )

    lines += ["", "## By scenario (behaviour passed / cases)", ""]
    scenarios = sorted({s for c in cfgs for s in cfgs[c]["summary"]["by_scenario"]})
    lines += ["| Scenario | " + " | ".join(cfgs) + " |", "|---|" + "---|" * len(cfgs)]
    for s in scenarios:
        cells = []
        for c in cfgs:
            v = cfgs[c]["summary"]["by_scenario"].get(s)
            cells.append(f"{v['passed']}/{v['cases']}" if v else "-")
        lines.append(f"| {s} | " + " | ".join(cells) + " |")

    lines += ["", "## Per-case results", ""]
    lines += [
        "| Case | Scenario | "
        + " | ".join(f"{c} behaviour / rank" for c in cfgs)
        + " |",
        "|---|---|" + "---|" * len(cfgs),
    ]
    for i, row in enumerate(first["cases"]):
        cells = []
        for c in cfgs:
            r = cfgs[c]["cases"][i]
            if r.get("skipped"):
                cells.append(f"skipped ({r['skipped']})")
                continue
            rank = (
                "-"
                if r["rank"] is None
                else ("miss" if r["rank"] == 0 else f"#{r['rank']}")
            )
            cells.append(
                f"{'pass' if r['behavior_ok'] else 'FAIL'} / {rank} ({r['outcome']})"
            )
        lines.append(
            f"| {row['case_id']} | {row['scenario']} | " + " | ".join(cells) + " |"
        )

    failures = [
        (c, r)
        for c in cfgs
        for r in cfgs[c]["cases"]
        if not r.get("skipped")
        and (not r["behavior_ok"] or r["retrieval_hit"] is False)
    ]
    lines += ["", "## Observed failure cases (automatic list)", ""]
    if failures:
        for c, r in failures:
            lines.append(
                f"- [{c}] **{r['case_id']}** ({r['scenario']}): outcome `{r['outcome']}`, "
                f"reasons {r['reason_codes']}, rank {r['rank']} - query `{r['query_id']}`"
            )
    else:
        lines.append("- None in this run.")

    if results.get("recommendation"):
        a, b = cfgs["A"]["summary"], cfgs["B"]["summary"]
        lines += ["", "## What changed and recommendation", ""]
        lines.append(
            "Configuration B adds BM25 keyword retrieval, Reciprocal Rank Fusion and a reranking "
            "stage on top of A's dense vector retrieval. C is B without the reranker, to show what "
            "the reranker adds for its latency cost."
        )
        for key, label in metrics[:8]:
            if a.get(key) is not None and b.get(key) is not None:
                lines.append(
                    f"- {label}: A={a[key]} B={b[key]} (delta {round(b[key] - a[key], 4):+})"
                )
        lat = (b["p50_latency_ms"] or 0) - (a["p50_latency_ms"] or 0)
        lines.append(f"- Median latency delta (B - A): {lat:+.1f} ms")
        rec = results["recommendation"]
        lines += [
            "",
            f"**Recommended configuration: {rec['config']}**, because {rec['why']}",
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("kis_eval_report_written", path=str(path))
