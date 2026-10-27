"""Pydantic schemas for document endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    """Public document representation."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    filename: str
    status: str
    size_bytes: int
    mime_type: str | None
    chunk_count: int
    content_hash: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentUploadResponse(BaseModel):
    """Response after successful document upload."""

    document: DocumentResponse
    job_id: uuid.UUID
    message: str = "Document uploaded. Ingestion job queued."


class DocumentListResponse(BaseModel):
    """Paginated list of documents."""

    items: list[DocumentResponse]
    next_cursor: str | None = None
    has_more: bool = False
