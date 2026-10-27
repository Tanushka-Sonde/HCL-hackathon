"""Rule-based query router (FR-07): documents, SQL tool, or both.

Deterministic keyword rules keep routing explainable in the drill-down;
the matched signals are recorded with every query event.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_PROJECT_ID_RE = re.compile(r"\bPRJ-\d{4}\b", re.IGNORECASE)

_DATA_SIGNALS: dict[str, re.Pattern[str]] = {
    "project_id": _PROJECT_ID_RE,
    "budget_or_spend": re.compile(
        r"\b(budget|budgets|spend|spent|spending|cost so far)\b", re.I
    ),
    "headcount": re.compile(
        r"\b(headcount|how many (people|employees|staff|members))\b", re.I
    ),
    "invoices": re.compile(r"\b(invoice|invoices|vendor payments?)\b", re.I),
    "project_list": re.compile(
        r"\b(list|show|which) (all |the )?(active )?projects\b", re.I
    ),
    "aggregate": re.compile(r"\b(total|sum of|count of)\b", re.I),
}

_DOC_SIGNALS: dict[str, re.Pattern[str]] = {
    "policy_terms": re.compile(
        r"\b(policy|policies|sop|procedure|manual|guideline|rule|rules|retention|"
        r"approval|approve|approver|allowed|permitted|required|requirement|limit|"
        r"per diem|reimburse\w*|threshold|steps?|process|deploy\w*|access)\b",
        re.I,
    ),
    "doc_id": re.compile(r"\b[A-Z]{2,4}-(POL|SOP|MAN)-\d{3}\b", re.I),
    "question_why_how": re.compile(
        r"^\s*(why|how do|how should|what does|what is the)\b", re.I
    ),
}


@dataclass
class RouteDecision:
    route: str  # "docs" | "sql_tool" | "both"
    data_signals: list[str] = field(default_factory=list)
    doc_signals: list[str] = field(default_factory=list)

    @property
    def needs_docs(self) -> bool:
        return self.route in ("docs", "both")

    @property
    def needs_tool(self) -> bool:
        return self.route in ("sql_tool", "both")


def route_query(query: str) -> RouteDecision:
    data = [name for name, rx in _DATA_SIGNALS.items() if rx.search(query)]
    docs = [name for name, rx in _DOC_SIGNALS.items() if rx.search(query)]
    # "aggregate" alone ("total retention period") is not enough for the tool.
    strong_data = [d for d in data if d != "aggregate"]
    if strong_data and any(d != "question_why_how" for d in docs):
        route = "both"
    elif strong_data:
        route = "sql_tool"
    else:
        route = "docs"
    return RouteDecision(route=route, data_signals=data, doc_signals=docs)


def strip_data_terms(query: str) -> str:
    """Remove project IDs from the text used for document retrieval."""
    return _PROJECT_ID_RE.sub(" ", query)
