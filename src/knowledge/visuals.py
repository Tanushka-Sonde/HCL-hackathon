"""Charts in answers (WP-6).

Two kinds of visual can accompany an answer:

retrieved_chart  the original chart image, when a cited evidence chunk is a
                 chart extracted at ingestion (served from /kis/assets/{id}).
generated_chart  a line or bar chart drawn by the UI from a spec. The spec
                 comes from the model (one fenced ```chart block) or, when the
                 user asks for a plot, directly from a cited table or SQL rows.
                 Every value must appear in the cited sources (or be a calc
                 result); otherwise the chart is dropped and CHART_REJECTED is
                 logged. A chart can never show a number the sources lack.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from src.knowledge.text import content_tokens, numbers_in

if TYPE_CHECKING:
    from src.knowledge.schemas import Citation, Evidence, ToolCall

CHART_BLOCK_RE = re.compile(r"```chart\s*(\{.*?\})\s*```", re.S | re.I)
PLOT_INTENT_RE = re.compile(
    r"\b(plot|chart|graph|visuali[sz]e|trend|bar chart|line chart)\b", re.I
)
_MAX_POINTS = 50
_MAX_SERIES = 4


def extract_chart_block(answer: str) -> tuple[str, dict[str, Any] | None]:
    """Remove the first ```chart block from the answer and parse it."""
    match = CHART_BLOCK_RE.search(answer)
    if not match:
        return answer, None
    cleaned = (answer[: match.start()] + answer[match.end() :]).strip()
    try:
        spec = json.loads(match.group(1))
    except json.JSONDecodeError:
        return cleaned, {"_invalid": "chart block is not valid JSON"}
    return cleaned, spec if isinstance(spec, dict) else {"_invalid": "not an object"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^\d.\-]", "", value.replace(",", ""))
        try:
            return float(cleaned) if cleaned not in ("", "-", ".") else None
        except ValueError:
            return None
    return None


def _norm(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def normalize_spec(spec: dict[str, Any]) -> dict[str, Any] | None:
    """Coerce a chart spec to the UI shape, or None if it is unusable."""
    labels = [str(x) for x in (spec.get("labels") or [])][:_MAX_POINTS]
    series_out = []
    for s in (spec.get("series") or [])[:_MAX_SERIES]:
        values = [_number(v) for v in (s.get("values") or [])][: len(labels)]
        if labels and len(values) == len(labels) and all(v is not None for v in values):
            series_out.append({"name": str(s.get("name") or "value"), "values": values})
    if not labels or not series_out:
        return None
    chart_type = str(spec.get("chart_type") or "bar").lower()
    return {
        "chart_type": chart_type if chart_type in ("line", "bar") else "bar",
        "title": str(spec.get("title") or "")[:120],
        "x_label": str(spec.get("x_label") or "")[:60],
        "y_label": str(spec.get("y_label") or "")[:60],
        "labels": labels,
        "series": series_out,
    }


def _source_numbers(
    source_ids: list[str], evidence: list[Evidence], tools: list[ToolCall]
) -> set[str]:
    texts = [ev.content for ev in evidence if ev.source_id in source_ids]
    texts += [
        json.dumps(tc.rows, default=str)
        for tc in tools
        if tc.source_id in source_ids and tc.status == "success"
    ]
    return numbers_in(" ".join(texts))


def check_values(
    spec: dict[str, Any],
    source_ids: list[str],
    evidence: list[Evidence],
    tools: list[ToolCall],
    calculations: list[dict[str, Any]],
) -> list[str]:
    """Values that are neither in the cited sources nor calc results."""
    allowed = _source_numbers(source_ids, evidence, tools)
    allowed |= {c["result"].replace(",", "") for c in calculations if c.get("result")}
    return [
        _norm(v) for s in spec["series"] for v in s["values"] if _norm(v) not in allowed
    ]


# ── Deterministic charts from a cited table or SQL rows ──────


def _parse_markdown_table(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue  # separator row
        rows.append(cells)
    return rows


def _spec_from_rows(
    header: list[str], rows: list[list[Any]], question: str, title: str
) -> dict[str, Any] | None:
    if len(rows) < 2:
        return None
    numeric = [
        i
        for i in range(1, len(header))
        if all(_number(r[i]) is not None for r in rows if i < len(r))
    ]
    if not numeric:
        return None
    asked = set(content_tokens(question))
    # Ignore words every numeric header shares ("USD"), so "profit (USD)"
    # selects the Profit column only.
    words = {i: set(content_tokens(header[i])) for i in numeric}
    shared = set.intersection(*words.values()) if words else set()
    wanted = [i for i in numeric if (words[i] - shared) & asked] or numeric
    spec = {
        "chart_type": "line"
        if re.search(r"\b(trend|over time|monthly|line)\b", question, re.I)
        else "bar",
        "title": title,
        "x_label": header[0],
        "y_label": ", ".join(header[i] for i in wanted[:_MAX_SERIES]),
        "labels": [str(r[0]) for r in rows][:_MAX_POINTS],
        "series": [
            {"name": header[i], "values": [_number(r[i]) for r in rows][:_MAX_POINTS]}
            for i in wanted[:_MAX_SERIES]
        ],
    }
    return normalize_spec(spec)


def chart_from_sources(
    question: str,
    evidence: list[Evidence],
    tools: list[ToolCall],
    cited: set[str],
) -> tuple[dict[str, Any], list[str]] | None:
    """Build a chart from cited SQL rows or the best cited table/chart chunk."""
    for tc in tools:
        if tc.status == "success" and tc.source_id in cited and tc.rows:
            header = list(tc.rows[0].keys())
            rows = [[row.get(h) for h in header] for row in tc.rows]
            title = f"{tc.template.replace('_', ' ').title()} ({tc.source_id})"
            spec = _spec_from_rows(header, rows, question, title)
            if spec:
                return spec, [tc.source_id]
    for ev in evidence:
        if ev.source_id not in cited or ev.content_type not in ("table", "chart"):
            continue
        parsed = _parse_markdown_table(ev.content)
        if len(parsed) < 3:
            continue
        spec = _spec_from_rows(parsed[0], parsed[1:], question, ev.title)
        if spec:
            return spec, [ev.source_id]
    return None


def build_visuals(
    *,
    question: str,
    model_spec: dict[str, Any] | None,
    evidence: list[Evidence],
    tools: list[ToolCall],
    citations: list[Citation],
    calculations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Return (visuals, rejection). ``rejection`` is logged as CHART_REJECTED."""
    cited = {c.source_id for c in citations if c.valid}
    visuals: list[dict[str, Any]] = []
    for ev in evidence:
        if ev.content_type == "chart" and ev.asset_id and ev.source_id in cited:
            first = ev.content.splitlines()[0] if ev.content else ""
            title = re.sub(r"^Chart:\s*|\s*\(page \d+\)$", "", first)
            visuals.append(
                {
                    "kind": "retrieved_chart",
                    "asset_url": f"/api/v1/kis/assets/{ev.asset_id}",
                    "source_id": ev.source_id,
                    "doc": ev.doc_id,
                    "page": ev.page,
                    "title": title,
                }
            )

    rejection = None
    spec, source_ids = None, []
    if model_spec is not None:
        if "_invalid" in model_spec:
            rejection = {"reason": model_spec["_invalid"]}
        else:
            source_ids = [s for s in (model_spec.get("source_ids") or []) if s in cited]
            spec = normalize_spec(model_spec)
            if spec is None or not source_ids:
                rejection = {"reason": "chart spec incomplete or cites no valid source"}
                spec = None
    if spec is None and rejection is None and PLOT_INTENT_RE.search(question):
        built = chart_from_sources(question, evidence, tools, cited)
        if built:
            spec, source_ids = built
    if spec is not None:
        missing = check_values(spec, source_ids, evidence, tools, calculations)
        if missing:
            rejection = {
                "reason": "values not found in cited sources",
                "values": missing[:10],
            }
        else:
            visuals.append(
                {"kind": "generated_chart", "spec": spec, "source_ids": source_ids}
            )
    return visuals, rejection
