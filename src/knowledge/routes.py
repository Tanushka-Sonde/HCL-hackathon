"""Knowledge service API (local demo mode).

Every endpoint except login requires a bearer token. Roles are enforced
here, server-side: ``user`` may only use the assistant; ``admin`` also gets
the knowledge base, observability, evaluation and user management.

Endpoints (prefix ``/api/v1/kis``):
    POST   /auth/login        Username + password -> JWT          (public)
    GET    /auth/me           Current user                        (any role)
    GET    /config            Active pipeline configuration       (any role)
    POST   /query             Ask a question                      (any role)
    POST   /feedback          Rate one of your own answers        (any role)
    GET    /admin/users       List users                          (admin)
    POST   /admin/users       Create a user                       (admin)

Admin only:
    POST   /ingest            Upload and index one document
    POST   /ingest/demo       Index the bundled synthetic demo corpus
    GET    /documents         List indexed documents
    DELETE /documents/{id}    Remove a document from the index
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

from fastapi import APIRouter, Depends, Form, Query, Request, UploadFile

from src.core.config import get_settings
from src.core.exceptions import NotFoundError, ValidationError
from src.core.logging import get_logger
from src.knowledge.auth import CurrentUser  # noqa: TC001 - FastAPI resolves it at runtime
from src.knowledge.evaluation import run_evaluation
from src.knowledge.metrics import compute_metrics, summarize_event
from src.knowledge.parsing import file_too_large_message
from src.knowledge.schemas import (
    DemoIngestResponse,
    DocumentInfo,
    EvalRunRequest,
    FeedbackRequest,
    IngestResponse,
    LoginRequest,
    LoginResponse,
    QueryRequest,
    QueryResponse,
    UserCreateRequest,
    UserInfo,
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


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def current_user(
    request: Request, svc: KnowledgeService = Depends(get_service)
) -> CurrentUser:
    """Any signed-in, active user (401 otherwise)."""
    return svc.auth.authenticate(request.headers.get("Authorization"))


def admin_user(
    request: Request,
    user: CurrentUser = Depends(current_user),
    svc: KnowledgeService = Depends(get_service),
) -> CurrentUser:
    """An admin (403 and a logged ``forbidden`` auth event otherwise)."""
    svc.auth.require_admin(user, request.url.path, _client_ip(request))
    return user


# ── Auth ─────────────────────────────────────────────────────


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    body: LoginRequest, request: Request, svc: KnowledgeService = Depends(get_service)
) -> LoginResponse:
    result = await asyncio.to_thread(
        svc.auth.login, body.username, body.password, _client_ip(request)
    )
    return LoginResponse(**result)


@router.get("/auth/me", response_model=UserInfo)
async def me(
    user: CurrentUser = Depends(current_user),
    svc: KnowledgeService = Depends(get_service),
) -> UserInfo:
    return UserInfo(**(svc.store.get_user(user.id) or {}))


@router.get("/admin/users", response_model=list[UserInfo])
async def list_users(
    _: CurrentUser = Depends(admin_user), svc: KnowledgeService = Depends(get_service)
) -> list[UserInfo]:
    return [UserInfo(**u) for u in svc.store.list_users()]


@router.post("/admin/users", response_model=UserInfo, status_code=201)
async def create_user(
    body: UserCreateRequest,
    _: CurrentUser = Depends(admin_user),
    svc: KnowledgeService = Depends(get_service),
) -> UserInfo:
    user = await asyncio.to_thread(
        svc.auth.create_user, body.username, body.password, body.role
    )
    return UserInfo(**user)


# ── Assistant (any role) ─────────────────────────────────────


@router.get("/config")
async def get_config(
    _: CurrentUser = Depends(current_user), svc: KnowledgeService = Depends(get_service)
) -> dict[str, Any]:
    return svc.describe()


@router.post("/query", response_model=QueryResponse)
async def query(
    body: QueryRequest,
    request: Request,
    user: CurrentUser = Depends(current_user),
    svc: KnowledgeService = Depends(get_service),
) -> QueryResponse:
    return await svc.query(
        body, correlation_id=getattr(request.state, "request_id", None), user=user
    )


@router.post("/feedback")
async def feedback(
    body: FeedbackRequest,
    user: CurrentUser = Depends(current_user),
    svc: KnowledgeService = Depends(get_service),
) -> dict[str, str]:
    event = svc.store.get_event(body.query_id)
    # Users may only rate their own answers; someone else's query is "not found".
    if event is None or (
        not user.is_admin and event["identity"].get("user_id") != user.id
    ):
        raise NotFoundError("Query", body.query_id)
    svc.add_feedback(body.query_id, body.helpful, body.comment, user_id=user.id)
    return {"status": "recorded"}


# ── Knowledge base (admin) ───────────────────────────────────


@router.post("/ingest", response_model=IngestResponse, status_code=201)
async def ingest(
    file: UploadFile,
    category: str | None = Form(default=None, max_length=50),
    version: str | None = Form(default=None, max_length=20),
    status: str | None = Form(default=None, max_length=20),
    effective_date: str | None = Form(default=None, max_length=10),
    user: CurrentUser = Depends(admin_user),
    svc: KnowledgeService = Depends(get_service),
) -> IngestResponse:
    limit = svc.settings.kis_max_upload_mb * 1_048_576
    if file.size is not None and file.size > limit:
        raise ValidationError(file_too_large_message(file.size, limit))
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise ValidationError(file_too_large_message(len(content), limit))
    metadata = {
        "category": category,
        "version": version,
        "status": status,
        "effective": effective_date,
    }
    return await asyncio.to_thread(
        svc.ingest, file.filename or "untitled.txt", content, metadata, user.id
    )


@router.post("/ingest/demo", response_model=DemoIngestResponse)
async def ingest_demo(
    _: CurrentUser = Depends(admin_user),
    svc: KnowledgeService = Depends(get_service),
) -> DemoIngestResponse:
    return await asyncio.to_thread(svc.ingest_demo)


@router.get("/documents", response_model=list[DocumentInfo])
async def list_documents(
    _: CurrentUser = Depends(admin_user),
    svc: KnowledgeService = Depends(get_service),
) -> list[DocumentInfo]:
    return svc.list_documents()


@router.get("/documents/{document_id}/chunks")
async def document_chunks(
    document_id: str,
    _: CurrentUser = Depends(admin_user),
    svc: KnowledgeService = Depends(get_service),
) -> list[dict[str, Any]]:
    """What chunking produced for one document (page, section, type)."""
    return svc.store.list_chunks(document_id)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    _: CurrentUser = Depends(admin_user),
    svc: KnowledgeService = Depends(get_service),
) -> None:
    if not svc.delete_document(document_id):
        raise NotFoundError("Document", document_id)


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
    _: CurrentUser = Depends(admin_user),
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
    _: CurrentUser = Depends(admin_user),
    svc: KnowledgeService = Depends(get_service),
) -> list[dict[str, Any]]:
    events = _filtered_events(svc, config_id, outcome, since_hours, include_eval, limit)
    return [summarize_event(e) for e in events]


@router.get("/queries/{query_id}")
async def get_query(
    query_id: str,
    _: CurrentUser = Depends(admin_user),
    svc: KnowledgeService = Depends(get_service),
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
    body: EvalRunRequest,
    _: CurrentUser = Depends(admin_user),
    svc: KnowledgeService = Depends(get_service),
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
async def eval_status(_: CurrentUser = Depends(admin_user)) -> dict[str, Any]:
    return {k: v for k, v in _eval_state.items() if k != "task"}
