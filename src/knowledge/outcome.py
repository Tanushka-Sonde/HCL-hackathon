"""Query outcome rules: Success / Partial-Fallback / Failed with reason codes.

An HTTP 200 does not mean success. Rules, evaluated in order:

FAILED
  STAGE_ERROR            an unhandled error in a pipeline stage
  TOOL_FAILED            the question needed the data tool, the tool failed,
                         and no document evidence could answer instead
PARTIAL (fallback)
  INJECTION_BLOCKED      the query tried to override the assistant's rules
  INSUFFICIENT_EVIDENCE  no relevant evidence/tool data, or the model declined
  TOOL_FAILED_PARTIAL    a tool failed but documents still answered
  LLM_FALLBACK           the LLM was unavailable; extractive answer returned
  NO_CITATIONS           an answer was given without any citation
  INVALID_CITATIONS      a citation does not map to returned evidence
  UNSUPPORTED_CLAIMS     grounding score below the configured threshold
  OUTPUT_TRUNCATED       the model stopped at the output token limit
SUCCESS
  OK                     evidence found, all citations valid, grounded,
                         no failed stage

Flags do not change the outcome: CONFLICT_SURFACED, EMBEDDED_INJECTION_REMOVED,
PII_MASKED (personal data or salaries masked for a user-role response),
EVIDENCE_TRIMMED_FOR_BUDGET (evidence dropped or cut to fit the input budget),
CHART_REJECTED (a chart had values not found in the cited sources; dropped).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.knowledge.schemas import Citation, ToolCall

REASON_DESCRIPTIONS: dict[str, str] = {
    "OK": "Grounded answer with valid citations",
    "STAGE_ERROR": "A pipeline stage raised an unhandled error",
    "TOOL_FAILED": "Required data tool failed and no other evidence was available",
    "INJECTION_BLOCKED": "Query attempted to override assistant rules",
    "INSUFFICIENT_EVIDENCE": "No relevant evidence; honest fallback returned",
    "TOOL_FAILED_PARTIAL": "Data tool failed; answered from documents only",
    "LLM_FALLBACK": "LLM unavailable; deterministic extractive answer",
    "NO_CITATIONS": "Answer contains no citations",
    "INVALID_CITATIONS": "Answer cites sources that were not returned",
    "UNSUPPORTED_CLAIMS": "Some claims are not supported by cited evidence",
    "OUTPUT_TRUNCATED": "The answer hit the output token limit and may be cut off",
}


def decide_outcome(
    *,
    stage_errors: dict[str, str],
    injection_blocked: bool,
    needs_tool: bool,
    evidence_found: bool,
    tool_calls: list[ToolCall],
    llm_status: str,
    answer_insufficient: bool,
    citations: list[Citation],
    grounding_score: float | None,
    grounding_threshold: float,
    output_truncated: bool = False,
) -> tuple[str, list[str]]:
    """Return (outcome, reason_codes)."""
    if stage_errors:
        return "failed", ["STAGE_ERROR"]

    tool_failed = any(tc.status == "error" for tc in tool_calls)
    tool_ok = any(tc.status == "success" and tc.row_count > 0 for tc in tool_calls)

    if needs_tool and tool_failed and not evidence_found:
        return "failed", ["TOOL_FAILED"]
    if injection_blocked:
        return "partial", ["INJECTION_BLOCKED"]
    if (not evidence_found and not tool_ok) or answer_insufficient:
        return "partial", ["INSUFFICIENT_EVIDENCE"]

    reasons: list[str] = []
    if tool_failed:
        reasons.append("TOOL_FAILED_PARTIAL")
    if llm_status != "ok":
        reasons.append("LLM_FALLBACK")
    if not citations:
        reasons.append("NO_CITATIONS")
    elif any(not c.valid for c in citations):
        reasons.append("INVALID_CITATIONS")
    if grounding_score is not None and grounding_score < grounding_threshold:
        reasons.append("UNSUPPORTED_CLAIMS")
    if output_truncated:
        reasons.append("OUTPUT_TRUNCATED")
    if reasons:
        return "partial", reasons
    return "success", ["OK"]


def confidence_for(
    outcome: str, grounding_score: float | None, top_relevance: float
) -> str:
    if outcome == "success" and (grounding_score or 0) >= 0.9 and top_relevance >= 0.75:
        return "high"
    if outcome == "success" or (outcome == "partial" and (grounding_score or 0) >= 0.7):
        return "medium"
    return "low"
