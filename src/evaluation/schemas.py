"""Pydantic schemas for evaluation endpoints."""

from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel, Field


class RelevanceGrade(str, Enum):
    """CRAG relevance grades."""

    RELEVANT = "relevant"
    AMBIGUOUS = "ambiguous"
    NOT_RELEVANT = "not_relevant"


class RelevanceRequest(BaseModel):
    """Request to evaluate chunk relevance against a query."""

    query: str = Field(min_length=1, max_length=2000)
    chunk_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)


class ChunkRelevance(BaseModel):
    """Relevance grade for a single chunk."""

    chunk_id: uuid.UUID
    grade: RelevanceGrade
    reasoning: str


class RelevanceResponse(BaseModel):
    """Evaluation results for one or more chunks."""

    query: str
    evaluations: list[ChunkRelevance]
    model: str
    circuit_state: str
