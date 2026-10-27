"""Output validation: citation mapping, claim grounding, conflict detection.

Grounding rule (documented, deterministic): an answer sentence is a
*supported claim* when it cites at least one valid source, at least 50% of
its content tokens appear in the cited sources, and every number it states
appears in the cited sources. Grounding score = supported / total claims.
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.knowledge.generation import INSUFFICIENT_ANSWER
from src.knowledge.schemas import Citation, Evidence, ToolCall
from src.knowledge.text import content_tokens, numbers_in, split_sentences

CITATION_RE = re.compile(r"\[((?:S|T)\d+)\]")
_TOKEN_SUPPORT = 0.5


def _source_texts(evidence: list[Evidence], tools: list[ToolCall]) -> dict[str, str]:
    texts = {
        ev.source_id: f"{ev.title} {ev.doc_id} version {ev.version} {ev.status} {ev.section or ''} {ev.content}"
        for ev in evidence
    }
    for tc in tools:
        if tc.status == "success":
            texts[tc.source_id] = (
                json.dumps(tc.rows, default=str) + " " + json.dumps(tc.params)
            )
    return texts


def validate_citations(
    answer: str, evidence: list[Evidence], tools: list[ToolCall]
) -> list[Citation]:
    """Every distinct citation tag, and whether it maps to returned evidence."""
    by_id = {ev.source_id: ev for ev in evidence}
    tools_by_id = {tc.source_id: tc for tc in tools}
    citations: list[Citation] = []
    for sid in dict.fromkeys(CITATION_RE.findall(answer)):
        if sid in by_id:
            ev = by_id[sid]
            citations.append(
                Citation(
                    source_id=sid,
                    valid=True,
                    target=f"{ev.filename} ({ev.doc_id} v{ev.version or '-'})",
                    page=ev.page,
                    section=ev.section,
                )
            )
        elif sid in tools_by_id and tools_by_id[sid].status == "success":
            tc = tools_by_id[sid]
            citations.append(
                Citation(
                    source_id=sid,
                    valid=True,
                    target=f"{tc.name}:{tc.template} {tc.params}",
                )
            )
        else:
            citations.append(Citation(source_id=sid, valid=False, target=None))
    return citations


def is_insufficient(answer: str) -> bool:
    return INSUFFICIENT_ANSWER.lower().rstrip(".") in answer.lower()


def assess_grounding(
    answer: str, evidence: list[Evidence], tools: list[ToolCall]
) -> dict[str, Any]:
    """Classify each answer sentence as supported or potentially unsupported."""
    texts = _source_texts(evidence, tools)
    supported: list[str] = []
    unsupported: list[dict[str, str]] = []
    for sentence in split_sentences(answer):
        if sentence.startswith("Note:") or is_insufficient(sentence):
            continue
        bare = CITATION_RE.sub("", sentence)
        tokens = set(content_tokens(bare))
        if not tokens:
            continue
        cited = [sid for sid in CITATION_RE.findall(sentence) if sid in texts]
        if not cited:
            unsupported.append({"claim": sentence, "reason": "no valid citation"})
            continue
        source = " ".join(texts[sid] for sid in cited)
        source_tokens = set(content_tokens(source))
        overlap = len(tokens & source_tokens) / len(tokens)
        missing_numbers = numbers_in(bare) - numbers_in(source)
        if overlap < _TOKEN_SUPPORT:
            unsupported.append(
                {
                    "claim": sentence,
                    "reason": f"low overlap with cited source ({overlap:.0%})",
                }
            )
        elif missing_numbers:
            unsupported.append(
                {
                    "claim": sentence,
                    "reason": f"numbers not in source: {', '.join(sorted(missing_numbers))}",
                }
            )
        else:
            supported.append(sentence)
    total = len(supported) + len(unsupported)
    return {
        "score": round(len(supported) / total, 4) if total else None,
        "claims": total,
        "supported": supported,
        "unsupported": unsupported,
        "rule": "cited + >=50% token overlap + all numbers present in cited source",
    }


def detect_conflicts(evidence: list[Evidence], min_relevance: float) -> list[str]:
    """FR-09: surface relevant evidence from different versions of one document."""
    families: dict[str, dict[str, Evidence]] = {}
    for ev in evidence:
        if ev.relevance < min_relevance or not ev.version:
            continue
        families.setdefault(ev.doc_id, {}).setdefault(ev.version, ev)
    notes = []
    for doc_id, versions in families.items():
        if len(versions) < 2:
            continue
        ordered = sorted(versions.values(), key=lambda e: e.status != "effective")
        desc = " vs ".join(
            f"version {e.version} ({e.status or 'unknown status'}, {e.filename}) [{e.source_id}]"
            for e in ordered
        )
        notes.append(f"{doc_id} '{ordered[0].title}' has conflicting versions: {desc}.")
    return notes
