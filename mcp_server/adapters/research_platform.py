"""MCP adapter for the AI Research Platform services.

The adapter owns process-level dependencies used by stdio MCP tools and
delegates all business behavior to ``src`` services. It intentionally keeps
MCP-specific imports out of this module so the core adapter can be unit tested
without the MCP SDK installed.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, get_settings
from src.core.database import Database
from src.documents import service as document_service
from src.documents.storage import ObjectStorage
from src.evaluation import service as evaluation_service
from src.evaluation.llm_gateway import LLMGateway
from src.ingestion import service as ingestion_service
from src.ingestion.pipeline import Embedder, SentenceTransformerEmbedder
from src.retrieval import service as retrieval_service
from src.tenants import service as tenant_service
from src.tenants.middleware import set_tenant_context


class ResearchPlatformMCPAdapter:
    """Small facade exposing platform use cases to MCP tools."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._database = Database(self._settings)
        self._storage: ObjectStorage | None = None
        self._embedder: Embedder | None = None
        self._llm_gateway: LLMGateway | None = None

    async def close(self) -> None:
        """Release pooled database connections."""
        await self._database.dispose()

    async def upload_document(
        self,
        *,
        user_id: str,
        tenant_id: str | None = None,
        filename: str,
        content_base64: str,
        idempotency_key: str,
        mime_type: str | None = None,
    ) -> dict[str, Any]:
        """Upload a base64-encoded document and queue ingestion."""
        parsed_user_id = _parse_uuid(user_id, "user_id")
        content = base64.b64decode(content_base64, validate=True)

        async with self._session() as session:
            resolved_tenant_id = await self._resolve_tenant_id(
                parsed_user_id, tenant_id, session
            )
            document, job = await document_service.upload_document(
                filename=filename,
                content=content,
                mime_type=mime_type,
                idempotency_key=idempotency_key,
                user_id=parsed_user_id,
                tenant_id=resolved_tenant_id,
                db=session,
                storage=await self._get_storage(),
            )
            await session.commit()

        return {
            "document": _document_to_dict(document),
            "job": _job_to_dict(job),
        }

    async def list_documents(
        self,
        *,
        user_id: str,
        tenant_id: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List non-deleted documents for a user."""
        parsed_user_id = _parse_uuid(user_id, "user_id")
        async with self._session() as session:
            resolved_tenant_id = await self._resolve_tenant_id(
                parsed_user_id, tenant_id, session
            )
            documents, next_cursor = await document_service.list_documents(
                parsed_user_id,
                resolved_tenant_id,
                session,
                cursor=cursor,
                limit=min(max(limit, 1), 100),
            )

        return {
            "items": [_document_to_dict(document) for document in documents],
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
        }

    async def get_document(
        self,
        *,
        user_id: str,
        tenant_id: str | None = None,
        document_id: str,
    ) -> dict[str, Any]:
        """Fetch one document scoped to a user."""
        parsed_user_id = _parse_uuid(user_id, "user_id")
        async with self._session() as session:
            resolved_tenant_id = await self._resolve_tenant_id(
                parsed_user_id, tenant_id, session
            )
            document = await document_service.get_document(
                _parse_uuid(document_id, "document_id"),
                parsed_user_id,
                resolved_tenant_id,
                session,
            )
        return _document_to_dict(document)

    async def search(
        self,
        *,
        user_id: str,
        tenant_id: str | None = None,
        query: str,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Run hybrid retrieval over a user's document corpus."""
        parsed_user_id = _parse_uuid(user_id, "user_id")
        async with self._session() as session:
            resolved_tenant_id = await self._resolve_tenant_id(
                parsed_user_id, tenant_id, session
            )
            results = await retrieval_service.hybrid_search(
                query=query,
                user_id=parsed_user_id,
                tenant_id=resolved_tenant_id,
                embedder=self._get_embedder(),
                db=session,
                top_k=min(max(top_k, 1), 50),
                candidate_multiplier=self._settings.retrieval_candidate_multiplier,
            )

        return {
            "query": query,
            "results": [_ranked_chunk_to_dict(result) for result in results],
            "total": len(results),
        }

    async def get_job(
        self,
        *,
        user_id: str,
        tenant_id: str | None = None,
        job_id: str,
    ) -> dict[str, Any] | None:
        """Fetch ingestion job status scoped to a user."""
        parsed_user_id = _parse_uuid(user_id, "user_id")
        async with self._session() as session:
            resolved_tenant_id = await self._resolve_tenant_id(
                parsed_user_id, tenant_id, session
            )
            job = await ingestion_service.get_job(
                _parse_uuid(job_id, "job_id"),
                parsed_user_id,
                resolved_tenant_id,
                session,
            )
        return _job_to_dict(job) if job is not None else None

    async def evaluate_relevance(
        self,
        *,
        user_id: str,
        tenant_id: str | None = None,
        query: str,
        chunk_ids: list[str],
    ) -> dict[str, Any]:
        """Grade retrieved chunks for relevance using the configured LLM."""
        parsed_chunk_ids = [
            _parse_uuid(chunk_id, "chunk_ids") for chunk_id in chunk_ids
        ]
        parsed_user_id = _parse_uuid(user_id, "user_id")

        async with self._session() as session:
            resolved_tenant_id = await self._resolve_tenant_id(
                parsed_user_id, tenant_id, session
            )
            evaluations = await evaluation_service.evaluate_relevance(
                query=query,
                chunk_ids=parsed_chunk_ids,
                user_id=parsed_user_id,
                tenant_id=resolved_tenant_id,
                db=session,
                gateway=self._get_llm_gateway(),
            )

        return {
            "query": query,
            "evaluations": [
                {
                    "chunk_id": str(evaluation.chunk_id),
                    "grade": evaluation.grade.value,
                    "reasoning": evaluation.reasoning,
                }
                for evaluation in evaluations
            ],
            "model": self._settings.llm_model_name,
            "circuit_state": self._get_llm_gateway().circuit_state,
        }

    def _session(self) -> AsyncSession:
        return self._database.session_factory()

    async def _get_storage(self) -> ObjectStorage:
        if self._storage is None:
            self._storage = ObjectStorage(self._settings)
            await self._storage.ensure_bucket()
        return self._storage

    def _get_embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = SentenceTransformerEmbedder(
                model_name=self._settings.embedding_model_name,
                dim=self._settings.embedding_dimension,
            )
        return self._embedder

    def _get_llm_gateway(self) -> LLMGateway:
        if self._llm_gateway is None:
            self._llm_gateway = LLMGateway(self._settings)
        return self._llm_gateway

    async def _resolve_tenant_id(
        self,
        user_id: uuid.UUID,
        tenant_id: str | None,
        session: AsyncSession,
    ) -> uuid.UUID:
        requested_tenant_id = _parse_uuid(tenant_id, "tenant_id") if tenant_id else None
        membership = await tenant_service.resolve_membership(
            user_id=user_id,
            org_id=requested_tenant_id,
            db=session,
        )
        await set_tenant_context(session, membership.org_id)
        return membership.org_id


def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid UUID.") from exc


def _json_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _document_to_dict(document: Any) -> dict[str, Any]:
    return {
        "id": str(document.id),
        "tenant_id": str(document.tenant_id),
        "filename": document.filename,
        "status": document.status,
        "size_bytes": document.size_bytes,
        "mime_type": document.mime_type,
        "chunk_count": document.chunk_count,
        "content_hash": document.content_hash,
        "created_at": _json_value(document.created_at),
        "updated_at": _json_value(document.updated_at),
    }


def _job_to_dict(job: Any) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "document_id": str(job.document_id),
        "tenant_id": str(job.tenant_id),
        "status": job.status,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "error_message": job.error_message,
        "claimed_at": _json_value(job.claimed_at),
        "started_at": _json_value(job.started_at),
        "completed_at": _json_value(job.completed_at),
        "created_at": _json_value(job.created_at),
    }


def _ranked_chunk_to_dict(chunk: Any) -> dict[str, Any]:
    return {
        "chunk_id": str(chunk.chunk_id),
        "document_id": str(chunk.document_id),
        "content": chunk.content,
        "chunk_index": chunk.chunk_index,
        "page_number": chunk.page_number,
        "score": chunk.score,
        "document_filename": chunk.document_filename,
    }
