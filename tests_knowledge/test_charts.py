"""Charts in answers: retrieved chart images and generated charts (WP-6)."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from test_vision import FakeVision  # tests_knowledge is on sys.path (rootdir import)

from src.knowledge import generation
from src.knowledge.auth import CurrentUser
from src.knowledge.generation import GenerationResult
from src.knowledge.schemas import Evidence, QueryRequest
from src.knowledge.service import KnowledgeService
from src.knowledge.visuals import extract_chart_block

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from fastapi.testclient import TestClient

    from src.core.config import Settings

PROFIT = [30000.0, 37000.0, 45000.0, 41000.0, 48000.0, 57000.0]


def test_extract_chart_block() -> None:
    text, spec = extract_chart_block(
        'Profit rose [S1].\n```chart\n{"chart_type": "line", "labels": ["a"]}\n```'
    )
    assert text == "Profit rose [S1]." and spec == {
        "chart_type": "line",
        "labels": ["a"],
    }
    _, bad = extract_chart_block("x ```chart {not json} ```")
    assert bad and "_invalid" in bad


def test_plot_request_builds_chart_from_cited_table(client: TestClient) -> None:
    body = client.post(
        "/api/v1/kis/query",
        json={
            "query": "Plot the monthly profit (USD) from the Monthly Profit and Loss Report 2026"
        },
    ).json()
    charts = [v for v in body["visuals"] if v["kind"] == "generated_chart"]
    assert len(charts) == 1
    spec = charts[0]["spec"]
    assert spec["labels"][0] == "Jan 2026" and spec["labels"][-1] == "Jun 2026"
    assert [s["name"] for s in spec["series"]] == ["Profit (USD)"]
    assert spec["series"][0]["values"] == PROFIT
    cited = {c["source_id"] for c in body["citations"] if c["valid"]}
    assert set(charts[0]["source_ids"]) <= cited


def test_chart_from_sql_rows(client: TestClient) -> None:
    body = client.post(
        "/api/v1/kis/query", json={"query": "Show a chart of all projects budget"}
    ).json()
    chart = next(v for v in body["visuals"] if v["kind"] == "generated_chart")
    assert chart["source_ids"] == ["T1"]
    assert chart["spec"]["labels"][0] == "PRJ-1001"
    assert chart["spec"]["series"][0]["values"][0] == 420000.0


def _llm_with_chart(values: list[int]):
    async def fake(query, evidence, tools, turns, settings, start, max_tokens=0):
        table = next(e for e in evidence if e.content_type == "table")
        spec = {
            "chart_type": "line",
            "title": "Monthly profit",
            "labels": ["Jan 2026", "Feb 2026", "Mar 2026"],
            "series": [{"name": "Profit", "values": values}],
            "source_ids": [table.source_id],
        }
        return GenerationResult(
            text=f"Monthly profit is shown below [{table.source_id}].\n```chart\n{json.dumps(spec)}\n```",
            mode="groq",
            status="ok",
            model="stub",
        )

    return fake


def _pnl_service(
    tmp_path: Path, settings: Settings, demo_dir: Path
) -> KnowledgeService:
    svc = KnowledgeService(
        settings.model_copy(update={"groq_api_key": "test-key"}),
        data_dir=tmp_path,
        demo_dir=demo_dir,
    )
    path = demo_dir / "corpus" / "FIN-RPT-010_Monthly_PnL_2026.pdf"
    svc.ingest(path.name, path.read_bytes())
    return svc


QUESTION = "Plot monthly profit (USD) in the Monthly Profit and Loss Report 2026"


def test_model_chart_accepted_when_grounded(
    tmp_path: Path,
    offline_settings: Settings,
    demo_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _pnl_service(tmp_path, offline_settings, demo_dir)
    monkeypatch.setattr(
        generation, "_generate_groq", _llm_with_chart([30000, 37000, 45000])
    )
    resp = asyncio.run(svc.query(QueryRequest(query=QUESTION)))
    assert "```chart" not in resp.answer
    chart = next(v for v in resp.visuals if v["kind"] == "generated_chart")
    assert chart["spec"]["series"][0]["values"] == [30000.0, 37000.0, 45000.0]
    assert "CHART_REJECTED" not in resp.flags


def test_model_chart_rejected_when_values_are_invented(
    tmp_path: Path,
    offline_settings: Settings,
    demo_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _pnl_service(tmp_path, offline_settings, demo_dir)
    monkeypatch.setattr(
        generation, "_generate_groq", _llm_with_chart([30000, 99999, 45000])
    )
    resp = asyncio.run(svc.query(QueryRequest(query=QUESTION)))
    assert not [v for v in resp.visuals if v["kind"] == "generated_chart"]
    assert "CHART_REJECTED" in resp.flags
    event = svc.store.get_event(resp.query_id)
    assert event["chart_rejection"]["values"] == ["99999"]


def test_retrieved_chart_is_returned_when_cited(
    tmp_path: Path, offline_settings: Settings, demo_dir: Path
) -> None:
    svc = KnowledgeService(offline_settings, data_dir=tmp_path, demo_dir=demo_dir)
    svc.vision = FakeVision()  # type: ignore[assignment]
    path = demo_dir / "corpus" / "FIN-RPT-011_Quarterly_Revenue_Review.pdf"
    svc.ingest(path.name, path.read_bytes())
    resp = asyncio.run(
        svc.query(QueryRequest(query="Show the quarterly revenue 2025 chart"))
    )
    retrieved = [v for v in resp.visuals if v["kind"] == "retrieved_chart"]
    assert retrieved and retrieved[0]["title"] == "Quarterly Revenue 2025 (USD)"
    asset_id = retrieved[0]["asset_url"].rsplit("/", 1)[-1]
    assert svc.asset_path(asset_id) is not None and retrieved[0]["page"] == 1


def test_users_do_not_get_charts_built_from_personal_data() -> None:
    ev = Evidence(
        source_id="S1",
        chunk_id="c",
        document_id="d",
        filename="f.txt",
        doc_id="HR-REC-020",
        title="Comp",
        content="Tom Becker has an annual salary of USD 121,500.",
        relevance=1.0,
    )
    chart = {"kind": "generated_chart", "spec": {}, "source_ids": ["S1"]}
    user = CurrentUser("u", "alice", "user")
    admin = CurrentUser("a", "admin", "admin")
    assert KnowledgeService._present("a", [ev], [], [], user, [chart])["visuals"] == []
    assert KnowledgeService._present("a", [ev], [], [], admin, [chart])["visuals"] == [
        chart
    ]
