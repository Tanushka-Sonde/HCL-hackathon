"""Document API routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user, get_db_session
from src.auth.models import User
from src.documents import service as doc_service
from src.documents.chunk_schemas import ChunkListResponse, ChunkResponse
from src.documents.schemas import (
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
)
from src.documents.storage import ObjectStorage
from src.tenants import service as tenant_service
from src.tenants.dependencies import get_current_tenant
from src.tenants.schemas import TenantContext

router = APIRouter(prefix="/documents", tags=["documents"])


def _get_storage(request: Request) -> ObjectStorage:
    """Lazy-initialize and cache ObjectStorage on app state."""
    if not hasattr(request.app.state, "storage"):
        from src.core.config import get_settings

        request.app.state.storage = ObjectStorage(get_settings())
    return request.app.state.storage


@router.post("", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    file: UploadFile,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
    storage: ObjectStorage = Depends(_get_storage),
) -> DocumentUploadResponse:
    """Upload a document for ingestion.

    Requires an ``Idempotency-Key`` header for safe retries.
    Duplicate content (by SHA-256) returns the existing document.
    """
    tenant_service.require_role(tenant.role, {"admin", "editor"})
    content = await file.read()
    document, job = await doc_service.upload_document(
        filename=file.filename or "untitled",
        content=content,
        mime_type=file.content_type,
        idempotency_key=idempotency_key,
        user_id=user.id,
        tenant_id=tenant.org_id,
        db=db,
        storage=storage,
    )
    return DocumentUploadResponse(
        document=DocumentResponse.model_validate(document),
        job_id=job.id,
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    cursor: str | None = None,
    limit: int = 20,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> DocumentListResponse:
    """List documents with cursor pagination."""
    docs, next_cursor = await doc_service.list_documents(
        user.id, tenant.org_id, db, cursor=cursor, limit=min(limit, 100)
    )
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in docs],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> DocumentResponse:
    """Get a single document by ID."""
    doc = await doc_service.get_document(document_id, user.id, tenant.org_id, db)
    return DocumentResponse.model_validate(doc)


@router.get("/{document_id}/chunks", response_model=ChunkListResponse)
async def list_chunks(
    document_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = 20,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> ChunkListResponse:
    """List chunks for a document with cursor pagination."""
    # Verify the document exists and belongs to this tenant
    await doc_service.get_document(document_id, user.id, tenant.org_id, db)
    chunks, next_cursor = await doc_service.list_chunks(
        document_id,
        tenant.org_id,
        db,
        cursor=cursor,
        limit=min(limit, 100),
    )
    return ChunkListResponse(
        items=[ChunkResponse.model_validate(c) for c in chunks],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
    storage: ObjectStorage = Depends(_get_storage),
) -> None:
    """Soft-delete a document and remove its file from storage."""
    tenant_service.require_role(tenant.role, {"admin", "editor"})
    await doc_service.soft_delete_document(
        document_id, user.id, tenant.org_id, db, storage
    )
