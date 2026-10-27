"""Pydantic schemas for ingestion job endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class JobResponse(BaseModel):
    """Public ingestion job representation."""

    id: uuid.UUID
    document_id: uuid.UUID
    tenant_id: uuid.UUID
    status: str
    attempt_count: int
    max_attempts: int
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}
