"""Structured-data SQL tool over a synthetic business dataset.

Security model: user text never becomes SQL. The tool selects one of a
fixed set of allowlisted, parameterised query templates, and parameters are
extracted with strict patterns (project IDs) or matched against an allowlist
(departments). Every execution returns provenance for citation ([T1]).

The ``vendor_invoices`` template intentionally targets a table that does not
exist in the demo dataset. It exists to demonstrate the controlled
tool-failure path and is labelled as a simulated failure.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger
from src.knowledge.schemas import ToolCall

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)

TOOL_NAME = "business_sql"
_PROJECT_ID_RE = re.compile(r"\bPRJ-(\d{4})\b", re.IGNORECASE)


@dataclass(frozen=True)
class QueryTemplate:
    name: str
    sql: str
    params: tuple[str, ...]
    description: str
    simulated_failure: bool = False


TEMPLATES: dict[str, QueryTemplate] = {
    t.name: t
    for t in (
        QueryTemplate(
            "project_budget",
            "SELECT project_id, name, department, owner, status, budget_usd, "
            "spent_usd, budget_usd - spent_usd AS remaining_usd "
            "FROM projects WHERE project_id = ?",
            ("project_id",),
            "Budget, spend and owner for one project",
        ),
        QueryTemplate(
            "project_headcount",
            "SELECT p.project_id, p.name, COUNT(a.employee_id) AS headcount "
            "FROM projects p LEFT JOIN assignments a ON a.project_id = p.project_id "
            "WHERE p.project_id = ? GROUP BY p.project_id, p.name",
            ("project_id",),
            "Number of employees assigned to a project",
        ),
        QueryTemplate(
            "department_spend",
            "SELECT department, COUNT(*) AS projects, SUM(budget_usd) AS total_budget_usd, "
            "SUM(spent_usd) AS total_spent_usd FROM projects WHERE department = ? "
            "GROUP BY department",
            ("department",),
            "Total budget and spend for a department",
        ),
        QueryTemplate(
            "list_projects",
            "SELECT project_id, name, department, status, budget_usd FROM projects "
            "ORDER BY project_id",
            (),
            "All projects",
        ),
        QueryTemplate(
            "vendor_invoices",
            "SELECT invoice_id, vendor, amount_usd, status FROM vendor_invoices "
            "WHERE project_id = ?",
            ("project_id",),
            "Vendor invoices for a project (SIMULATED FAILURE: table not provisioned)",
            simulated_failure=True,
        ),
    )
}


class SQLTool:
    """Executes allowlisted templates against the demo business database."""

    def __init__(self, db_path: Path, seed_path: Path | None = None) -> None:
        self._db_path = db_path
        if not db_path.exists() and seed_path is not None and seed_path.exists():
            build_business_db(db_path, seed_path)
        self.departments = self._load_departments()

    def _connect(self) -> sqlite3.Connection:
        # Read-only connection: the tool can never modify business data.
        conn = sqlite3.connect(f"file:{self._db_path.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _load_departments(self) -> list[str]:
        if not self._db_path.exists():
            return []
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT department FROM projects"
                ).fetchall()
            return sorted(r["department"] for r in rows)
        except sqlite3.Error:
            return []

    # ── Planning ─────────────────────────────────────────────

    def plan(self, query: str) -> tuple[QueryTemplate | None, dict[str, Any], str]:
        """Pick a template and extract validated parameters.

        Returns (template, params, reason). Template is None if nothing fits.
        """
        q = query.lower()
        project = _PROJECT_ID_RE.search(query)
        project_id = f"PRJ-{project.group(1)}" if project else None
        department = next((d for d in self.departments if d.lower() in q), None)

        if re.search(r"\b(invoice|invoices|vendor payments?)\b", q):
            name = "vendor_invoices"
        elif re.search(r"\b(headcount|how many (people|employees|staff|members))\b", q):
            name = "project_headcount"
        elif project_id:
            name = "project_budget"
        elif department:
            name = "department_spend"
        elif re.search(r"\bprojects\b", q):
            name = "list_projects"
        else:
            return None, {}, "no template matches the question"

        template = TEMPLATES[name]
        params: dict[str, Any] = {}
        for p in template.params:
            if p == "project_id":
                if not project_id:
                    return (
                        None,
                        {},
                        f"template '{name}' needs a project ID like PRJ-1001",
                    )
                params[p] = project_id
            elif p == "department":
                params[p] = department
        return template, params, f"matched template '{name}'"

    # ── Execution ────────────────────────────────────────────

    def run(self, query: str, source_id: str = "T1") -> ToolCall:
        template, params, reason = self.plan(query)
        if template is None:
            return ToolCall(
                source_id=source_id,
                name=TOOL_NAME,
                template="none",
                status="skipped",
                result_summary=reason,
            )
        return self.execute(template.name, params, source_id)

    def execute(
        self, template_name: str, params: dict[str, Any], source_id: str = "T1"
    ) -> ToolCall:
        """Execute an allowlisted template by name with validated params."""
        template = TEMPLATES.get(template_name)
        if template is None:
            raise ValueError(f"Template '{template_name}' is not allowlisted.")
        for p in template.params:
            value = params.get(p)
            if p == "project_id" and not (
                isinstance(value, str) and re.fullmatch(r"PRJ-\d{4}", value)
            ):
                raise ValueError("project_id must look like PRJ-1234")
            if p == "department" and value not in self.departments:
                raise ValueError("department is not in the allowlist")

        start = time.perf_counter()
        try:
            with self._connect() as conn:
                rows = [
                    dict(r)
                    for r in conn.execute(
                        template.sql, [params[p] for p in template.params]
                    ).fetchall()
                ]
            latency = (time.perf_counter() - start) * 1000
            summary = (
                f"{len(rows)} row(s) from template '{template.name}'"
                if rows
                else f"no rows for {params}"
            )
            return ToolCall(
                source_id=source_id,
                name=TOOL_NAME,
                template=template.name,
                params=params,
                status="success",
                row_count=len(rows),
                latency_ms=round(latency, 2),
                result_summary=summary,
                rows=rows[:20],
            )
        except sqlite3.Error as exc:
            latency = (time.perf_counter() - start) * 1000
            logger.warning("kis_tool_failed", template=template.name, error=str(exc))
            return ToolCall(
                source_id=source_id,
                name=TOOL_NAME,
                template=template.name,
                params=params,
                status="error",
                latency_ms=round(latency, 2),
                result_summary="tool execution failed",
                # Plain message for the user; the raw driver error stays in the
                # stored event (error_detail) and is stripped from API responses.
                error="The business data source could not be queried.",
                error_detail=f"{type(exc).__name__}: {exc}",
                simulated_failure=template.simulated_failure,
            )


def build_business_db(db_path: Path, seed_path: Path) -> None:
    """Create the synthetic business database from its SQL seed file."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(seed_path.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    logger.info("kis_business_db_built", path=str(db_path))
