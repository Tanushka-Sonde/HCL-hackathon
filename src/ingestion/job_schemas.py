"""Pydantic schemas for paginated job listing."""

from __future__ import annotations

from pydantic import BaseModel

from src.ingestion.schemas import JobResponse


class JobListResponse(BaseModel):
    """Paginated list of ingestion jobs."""

    items: list[JobResponse]
    next_cursor: str | None = None
    has_more: bool = False
