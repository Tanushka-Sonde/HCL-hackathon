"""Knowledge service API (local demo mode).

Endpoints (prefix ``/api/v1/kis``):
    GET    /config            Active pipeline configuration
    POST   /ingest            Upload and index one document
    POST   /ingest/demo       Index the bundled synthetic demo corpus
    GET    /documents         List indexed documents
    DELETE /documents/{id}    Remove a document from the index
    POST   /query             Ask a question (grounded answer + citations)
    POST   /feedback          Helpful / not-helpful feedback
    GET    /metrics           Aggregate dashboard KPIs
    GET    /queries           Recent query events (summaries)
    GET    /queries/{id}      Full per-query drill-down event
    POST   /eval/run          Start the A/B evaluation run (background)
    GET    /eval/status       Status / results of the latest evaluation run
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, UploadFile

from src.core.config import get_settings
from src.core.exceptions import NotFoundError, ValidationError
from src.core.logging import get_logger
from src.knowledge.evaluation import run_evaluation
from src.knowledge.metrics import compute_metrics, summarize_event
from src.knowledge.schemas import (
    DemoIngestResponse,
    DocumentInfo,
    EvalRunRequest,
    FeedbackRequest,
    IngestResponse,
    QueryRequest,
    QueryResponse,
)
from src.knowledge.service import KnowledgeService

logger = get_logger(__name__)

router = APIRouter(prefix="/kis", tags=["knowledge"])

_service: KnowledgeService | None = None
_service_lock = threading.Lock()
_eval_state: dict[str, Any] = {"status": "idle"}


def get_service() -> KnowledgeService:
    """Process-wide knowledge service (models load once, on first use)."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = KnowledgeService(get_settings())
    return _service


@router.get("/config")
async def get_config(svc: KnowledgeService = Depends(get_service)) -> dict[str, Any]:
    return svc.describe()


@router.post("/ingest", response_model=IngestResponse, status_code=201)
async def ingest(
    file: UploadFile, svc: KnowledgeService = Depends(get_service)
) -> IngestResponse:
    limit = svc.settings.kis_max_upload_mb * 1_048_576
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise ValidationError(
            f"File exceeds the {svc.settings.kis_max_upload_mb} MB limit."
        )
    return await asyncio.to_thread(svc.ingest, file.filename or "untitled.txt", content)


@router.post("/ingest/demo", response_model=DemoIngestResponse)
async def ingest_demo(
    svc: KnowledgeService = Depends(get_service),
) -> DemoIngestResponse:
    return await asyncio.to_thread(svc.ingest_demo)


@router.get("/documents", response_model=list[DocumentInfo])
async def list_documents(
    svc: KnowledgeService = Depends(get_service),
) -> list[DocumentInfo]:
    return svc.list_documents()


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: str, svc: KnowledgeService = Depends(get_service)
) -> None:
    if not svc.delete_document(document_id):
        raise NotFoundError("Document", document_id)


@router.post("/query", response_model=QueryResponse)
async def query(
    body: QueryRequest, request: Request, svc: KnowledgeService = Depends(get_service)
) -> QueryResponse:
    return await svc.query(
        body, correlation_id=getattr(request.state, "request_id", None)
    )


@router.post("/feedback")
async def feedback(
    body: FeedbackRequest, svc: KnowledgeService = Depends(get_service)
) -> dict[str, str]:
    if not svc.add_feedback(body.query_id, body.helpful, body.comment):
        raise NotFoundError("Query", body.query_id)
    return {"status": "recorded"}


def _filtered_events(
    svc: KnowledgeService,
    config_id: str | None,
    outcome: str | None,
    since_hours: float | None,
    include_eval: bool,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    since = None
    if since_hours:
        since = (datetime.now(UTC) - timedelta(hours=since_hours)).isoformat(
            timespec="milliseconds"
        )
    return svc.store.list_events(
        config_id=config_id,
        outcome=outcome,
        since=since,
        include_eval=include_eval,
        limit=limit,
    )


@router.get("/metrics")
async def metrics(
    config_id: str | None = Query(default=None, pattern="^[AB]$"),
    outcome: str | None = Query(default=None, pattern="^(success|partial|failed)$"),
    since_hours: float | None = Query(default=None, gt=0, le=24 * 365),
    include_eval: bool = True,
    svc: KnowledgeService = Depends(get_service),
) -> dict[str, Any]:
    events = _filtered_events(svc, config_id, outcome, since_hours, include_eval)
    return compute_metrics(events, svc.settings.kis_grounding_threshold)


@router.get("/queries")
async def list_queries(
    config_id: str | None = Query(default=None, pattern="^[AB]$"),
    outcome: str | None = Query(default=None, pattern="^(success|partial|failed)$"),
    since_hours: float | None = Query(default=None, gt=0, le=24 * 365),
    include_eval: bool = True,
    limit: int = Query(default=50, ge=1, le=500),
    svc: KnowledgeService = Depends(get_service),
) -> list[dict[str, Any]]:
    events = _filtered_events(svc, config_id, outcome, since_hours, include_eval, limit)
    return [summarize_event(e) for e in events]


@router.get("/queries/{query_id}")
async def get_query(
    query_id: str, svc: KnowledgeService = Depends(get_service)
) -> dict[str, Any]:
    event = svc.store.get_event(query_id)
    if event is None:
        raise NotFoundError("Query", query_id)
    return event


async def _run_eval_background(svc: KnowledgeService, configs: list[str]) -> None:
    try:
        _eval_state["result"] = await run_evaluation(svc, configs)
        _eval_state["status"] = "completed"
    except Exception as exc:
        logger.exception("kis_eval_failed")
        _eval_state["status"] = "failed"
        _eval_state["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    finally:
        _eval_state["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")


@router.post("/eval/run", status_code=202)
async def start_eval(
    body: EvalRunRequest, svc: KnowledgeService = Depends(get_service)
) -> dict[str, Any]:
    if _eval_state.get("status") == "running":
        return {"status": "running", "started_at": _eval_state.get("started_at")}
    _eval_state.clear()
    _eval_state.update(
        status="running", started_at=datetime.now(UTC).isoformat(timespec="seconds")
    )
    _eval_state["task"] = asyncio.create_task(
        _run_eval_background(svc, list(dict.fromkeys(body.configs)))
    )
    return {"status": "running", "started_at": _eval_state["started_at"]}


@router.get("/eval/status")
async def eval_status() -> dict[str, Any]:
    return {k: v for k, v in _eval_state.items() if k != "task"}
