"""Pydantic schemas for chunk listing endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ChunkResponse(BaseModel):
    """Public chunk representation."""

    id: uuid.UUID
    document_id: uuid.UUID
    content: str
    chunk_index: int
    page_number: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChunkListResponse(BaseModel):
    """Paginated list of chunks."""

    items: list[ChunkResponse]
    next_cursor: str | None = None
    has_more: bool = False
