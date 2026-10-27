"""Aggregate KPIs for the observability dashboard (brief section 8.1).

All KPIs are computed from stored query events; nothing is simulated.
Execution success (HTTP 200) is reported separately from AI-quality outcome.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np


def _pct(values: list[float], q: float) -> float | None:
    return round(float(np.percentile(values, q)), 2) if values else None


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def compute_metrics(
    events: list[dict[str, Any]], grounding_threshold: float
) -> dict[str, Any]:
    total = len(events)
    outcomes = Counter(e["outcome"]["status"] for e in events)
    reasons = Counter(r for e in events for r in e["outcome"]["reason_codes"])
    flags = Counter(f for e in events for f in e["outcome"].get("flags", []))

    retrieval_ran = [
        e
        for e in events
        if e["execution"]["stages"].get("retrieval") in ("ok", "empty_index")
    ]
    retrieval_hits = sum(
        1 for e in retrieval_ran if e["evidence_quality"]["evidence_found"]
    )

    graded = [e for e in events if e["grounding"]["score"] is not None]
    grounded = sum(1 for e in graded if e["grounding"]["score"] >= grounding_threshold)

    answered = [
        e
        for e in events
        if not e["safety"]["injection_blocked"]
        and "INSUFFICIENT_EVIDENCE" not in e["outcome"]["reason_codes"]
        and "STAGE_ERROR" not in e["outcome"]["reason_codes"]
    ]
    cited_ok = sum(
        1
        for e in answered
        if e["citations"] and all(c["valid"] for c in e["citations"])
    )

    tool_calls = [
        tc for e in events for tc in e["tool_calls"] if tc["status"] != "skipped"
    ]
    tool_ok = sum(1 for tc in tool_calls if tc["status"] == "success")

    safety_query = sum(1 for e in events if e["safety"]["query_injection"])
    safety_chunk = sum(1 for e in events if e["safety"]["chunk_injections"])
    # pii_redactions: events recorded before role-based masking existed.
    safety_pii = sum(
        1
        for e in events
        if e["safety"].get("pii_masked") or e["safety"].get("pii_redactions")
    )
    safety_any = sum(1 for e in events if e["safety"]["events"])

    def lat(key: str, only_positive: bool = True) -> dict[str, float | None]:
        vals = [
            e["performance"][key]
            for e in events
            if not only_positive or e["performance"][key] > 0
        ]
        return {"p50": _pct(vals, 50), "p95": _pct(vals, 95), "n": len(vals)}

    in_tok = sum(e["usage"]["input_tokens"] for e in events)
    out_tok = sum(e["usage"]["output_tokens"] for e in events)
    cost = sum(e["usage"]["estimated_cost_usd"] for e in events)

    fb = [e["feedback"] for e in events if e.get("feedback")]
    helpful = sum(1 for f in fb if f["helpful"])

    by_config: dict[str, dict[str, Any]] = {}
    for cfg in sorted({e["identity"]["config_id"] for e in events}):
        evs = [e for e in events if e["identity"]["config_id"] == cfg]
        succ = sum(1 for e in evs if e["outcome"]["status"] == "success")
        totals = [e["performance"]["total_ms"] for e in evs]
        by_config[cfg] = {
            "total": len(evs),
            "success_rate": _rate(succ, len(evs)),
            "p50_total_ms": _pct(totals, 50),
        }

    return {
        "total_queries": total,
        "execution": {
            "http_ok": sum(1 for e in events if e["execution"]["http_status"] == 200),
            "stage_errors": sum(1 for e in events if e["errors"]),
        },
        "outcomes": {
            k: {"count": outcomes.get(k, 0), "rate": _rate(outcomes.get(k, 0), total)}
            for k in ("success", "partial", "failed")
        },
        "reason_codes": dict(reasons.most_common()),
        "flags": dict(flags.most_common()),
        "retrieval_success": {
            "count": retrieval_hits,
            "of": len(retrieval_ran),
            "rate": _rate(retrieval_hits, len(retrieval_ran)),
        },
        "grounding_rate": {
            "count": grounded,
            "of": len(graded),
            "rate": _rate(grounded, len(graded)),
        },
        "citation_support": {
            "count": cited_ok,
            "of": len(answered),
            "rate": _rate(cited_ok, len(answered)),
        },
        "tool_success": {
            "count": tool_ok,
            "of": len(tool_calls),
            "rate": _rate(tool_ok, len(tool_calls)),
        },
        "safety_events": {
            "queries_with_events": safety_any,
            "query_injection": safety_query,
            "embedded_injection": safety_chunk,
            "pii_masked": safety_pii,
        },
        "latency_ms": {
            "retrieval": lat("retrieval_ms"),
            "tool": lat("tool_ms"),
            "llm": lat("llm_ms"),
            "total": lat("total_ms", only_positive=False),
        },
        "usage": {
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "estimated_cost_usd": round(cost, 6),
            "avg_cost_per_query_usd": round(cost / total, 8) if total else None,
        },
        "feedback": {
            "helpful": helpful,
            "not_helpful": len(fb) - helpful,
            "rate_helpful": _rate(helpful, len(fb)),
        },
        "by_config": by_config,
    }


def summarize_event(e: dict[str, Any]) -> dict[str, Any]:
    """Compact row for the recent-queries table."""
    sources = sorted(
        {
            ev["filename"]
            for ev in e.get("evidence", [])
            if ev.get("relevance", 0) >= e["evidence_quality"]["threshold"]
        }
    )
    citations = e["citations"]
    return {
        "query_id": e["identity"]["query_id"],
        "timestamp": e["identity"]["timestamp"],
        "session_id": e["identity"]["session_id"],
        "config_id": e["identity"]["config_id"],
        "query": e["question"]["original"],
        "route": e["question"]["route"],
        "outcome": e["outcome"]["status"],
        "reason_codes": e["outcome"]["reason_codes"],
        "flags": e["outcome"].get("flags", []),
        "total_ms": e["performance"]["total_ms"],
        "sources": sources,
        "citations": len(citations),
        "citations_valid": bool(citations) and all(c["valid"] for c in citations),
        "grounding_score": e["grounding"]["score"],
        "tool_status": e["tool_calls"][0]["status"] if e["tool_calls"] else None,
        "safety_events": e["safety"]["events"],
        "feedback": e.get("feedback"),
        "eval_run_id": (e.get("eval") or {}).get("run_id"),
    }
