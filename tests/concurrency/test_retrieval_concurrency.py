"""Tests for concurrency behavior in retrieval."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.pipeline import SentenceTransformerEmbedder
from src.retrieval.service import hybrid_search


@pytest.mark.asyncio
async def test_hybrid_search_concurrency_success(db_session: AsyncSession) -> None:
    """Verify that hybrid_search successfully executes concurrently using independent sessions.

    If it used a single session concurrently, SQLAlchemy would raise IllegalStateChangeError.
    """
    embedder = SentenceTransformerEmbedder(model_name="all-MiniLM-L6-v2", dim=384)
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # This should succeed without raising any concurrency errors
    results = await hybrid_search(
        query="test concurrency",
        user_id=user_id,
        tenant_id=tenant_id,
        embedder=embedder,
        db=db_session,
        top_k=2,
    )
    # If we get here, no concurrency error was raised!
    assert isinstance(results, list)
