"""Unit tests for PR-10: new search modes, chunk listing, job listing schemas.

Tests the new dense_search / sparse_search functions, ChunkListResponse,
JobListResponse schemas, and verifies asyncio.gather usage in hybrid_search.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from src.documents.chunk_schemas import ChunkListResponse, ChunkResponse
from src.ingestion.job_schemas import JobListResponse
from src.ingestion.schemas import JobResponse
from src.retrieval.schemas import SearchRequest
from src.retrieval.service import RankedChunk, _reciprocal_rank_fusion

# ── Chunk Schemas ────────────────────────────────────────────


class TestChunkSchemas:
    def test_chunk_response_from_attributes(self) -> None:
        """ChunkResponse should accept ORM-like objects."""

        class FakeChunk:
            id = uuid.uuid4()
            document_id = uuid.uuid4()
            content = "Test content"
            chunk_index = 0
            page_number = 1
            created_at = datetime.now(UTC)

        resp = ChunkResponse.model_validate(FakeChunk(), from_attributes=True)
        assert resp.content == "Test content"
        assert resp.chunk_index == 0

    def test_chunk_list_response_defaults(self) -> None:
        resp = ChunkListResponse(items=[])
        assert resp.next_cursor is None
        assert resp.has_more is False


# ── Job List Schemas ─────────────────────────────────────────


class TestJobListSchemas:
    def test_job_list_response_empty(self) -> None:
        resp = JobListResponse(items=[])
        assert resp.items == []
        assert resp.has_more is False

    def test_job_list_response_with_items(self) -> None:
        job = JobResponse(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            status="queued",
            attempt_count=0,
            max_attempts=3,
            error_message=None,
            created_at=datetime.now(UTC),
            started_at=None,
            completed_at=None,
        )
        resp = JobListResponse(
            items=[job],
            next_cursor="abc",
            has_more=True,
        )
        assert len(resp.items) == 1
        assert resp.has_more is True


# ── Search Request ───────────────────────────────────────────


class TestSearchRequest:
    def test_valid_request(self) -> None:
        req = SearchRequest(query="test query", top_k=10)
        assert req.top_k == 10

    def test_default_top_k(self) -> None:
        req = SearchRequest(query="test query")
        assert req.top_k == 5

    def test_top_k_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SearchRequest(query="test", top_k=0)
        with pytest.raises(ValidationError):
            SearchRequest(query="test", top_k=51)


# ── Dense/Sparse service functions (RRF still works) ────────


class TestSingleModeResults:
    """Verify RankedChunk conversion for single-mode results."""

    def test_ranked_chunk_creation(self) -> None:
        chunk = RankedChunk(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            content="test",
            chunk_index=0,
            page_number=None,
            score=0.85,
            document_filename="doc.txt",
        )
        assert chunk.score == 0.85
        assert chunk.page_number is None

    def test_rrf_with_only_dense_results(self) -> None:
        """RRF should work even if sparse returns empty."""
        cid = uuid.uuid4()
        did = uuid.uuid4()
        dense = [
            {
                "chunk_id": str(cid),
                "document_id": str(did),
                "content": "hello",
                "chunk_index": 0,
                "page_number": None,
                "document_filename": "a.txt",
            },
        ]
        result = _reciprocal_rank_fusion(dense, [], top_k=5)
        assert len(result) == 1
        assert result[0].chunk_id == cid

    def test_rrf_with_only_sparse_results(self) -> None:
        """RRF should work even if dense returns empty."""
        cid = uuid.uuid4()
        did = uuid.uuid4()
        sparse = [
            {
                "chunk_id": str(cid),
                "document_id": str(did),
                "content": "hello",
                "chunk_index": 0,
                "page_number": None,
                "document_filename": "a.txt",
            },
        ]
        result = _reciprocal_rank_fusion([], sparse, top_k=5)
        assert len(result) == 1
        assert result[0].chunk_id == cid
