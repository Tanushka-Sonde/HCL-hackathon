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


def _sentences_with_tags(answer: str) -> list[tuple[str, list[str]]]:
    """Each sentence with the citation tags that cover it.

    A sentence without its own tag is covered by the next tag in the same
    paragraph ("Fact one. Fact two [S1]." -> both cite S1). A tag never
    reaches back across a paragraph break.
    """
    out: list[tuple[str, list[str]]] = []
    for paragraph in answer.split("\n"):
        sentences = split_sentences(paragraph)
        tags = [CITATION_RE.findall(s) for s in sentences]
        for i, sentence in enumerate(sentences):
            covering = tags[i] or next((t for t in tags[i + 1 :] if t), [])
            out.append((sentence, covering))
    return out


def is_insufficient(answer: str) -> bool:
    return INSUFFICIENT_ANSWER.lower().rstrip(".") in answer.lower()


def _calc_results(
    calculations: list[dict[str, Any]] | None,
) -> list[tuple[str, set[str]]]:
    """(result, operands) for each successful calculation, numbers normalized."""
    out = []
    for calc in calculations or []:
        if calc.get("result") is not None:
            out.append((calc["result"].replace(",", ""), numbers_in(calc["expr"])))
    return out


def assess_grounding(
    answer: str,
    evidence: list[Evidence],
    tools: list[ToolCall],
    calculations: list[dict[str, Any]] | None = None,
    question: str | None = None,
) -> dict[str, Any]:
    """Classify each answer sentence as supported or potentially unsupported.

    A computed number (from a ``{{calc: ...}}`` expression) counts as present
    in the source when every operand of its expression is in the cited source.
    Numbers the user gave in the question ("the last 5 months") are not claims.
    A paragraph's trailing citation also covers the sentences before it.
    """
    texts = _source_texts(evidence, tools)
    calcs = _calc_results(calculations)
    given = numbers_in(question or "")
    supported: list[str] = []
    unsupported: list[dict[str, str]] = []
    for sentence, tags in _sentences_with_tags(answer):
        if sentence.startswith("Note:") or is_insufficient(sentence):
            continue
        bare = CITATION_RE.sub("", sentence)
        tokens = set(content_tokens(bare))
        if not tokens:
            continue
        cited = [sid for sid in tags if sid in texts]
        if not cited:
            unsupported.append({"claim": sentence, "reason": "no valid citation"})
            continue
        source = " ".join(texts[sid] for sid in cited)
        source_tokens = set(content_tokens(source))
        overlap = len(tokens & source_tokens) / len(tokens)
        source_numbers = numbers_in(source)
        derived = {result for result, operands in calcs if operands <= source_numbers}
        missing_numbers = numbers_in(bare) - source_numbers - derived - given
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
        "rule": (
            "cited + >=50% token overlap + all numbers present in cited source "
            "(or computed by a calc whose operands are all in the source, "
            "or stated by the user in the question)"
        ),
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
