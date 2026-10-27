"""Integration tests for document upload and hybrid search."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings
from src.core.security import create_access_token
from tests.factories import create_test_user

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_upload_ingest_search(
    client: AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    """Test full upload, ingestion, and search workflow."""

    # 1. Setup user and auth
    user = await create_test_user(db_session, email="searcher@example.com")
    from tests.factories import get_user_workspace

    workspace = await get_user_workspace(user, db_session)
    token = create_access_token(str(user.id), user.email, settings)
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "search-test-1"}

    # 2. Upload document
    content = b"The quick brown fox jumps over the lazy dog. This document is about animal testing."
    files = {"file": ("fox.txt", content, "text/plain")}
    resp = await client.post("/api/v1/documents", files=files, headers=headers)
    assert resp.status_code == 201

    data = resp.json()
    doc_id = uuid.UUID(data["document"]["id"])
    job_id = uuid.UUID(data["job_id"])

    # 3. Manually simulate the ingestion worker
    # In a real system, the daemon picks this up. For the test, we process it directly.
    from src.ingestion.pipeline import IngestionPipeline, SentenceTransformerEmbedder
    from src.ingestion.service import claim_next_job, complete_job

    # Claim the job
    job = await claim_next_job(worker_id="test-worker", db=db_session)
    assert job is not None
    assert job.id == job_id

    # Process it
    embedder = SentenceTransformerEmbedder(
        model_name=settings.embedding_model_name,
        dim=settings.embedding_dimension,
    )
    pipeline = IngestionPipeline(embedder=embedder)
    chunks = pipeline.process(content, "text/plain")

    # Complete job (this writes chunks to the DB)
    await complete_job(
        job_id=job.id,
        document_id=doc_id,
        chunks=chunks,
        user_id=user.id,
        tenant_id=workspace.id,
        db=db_session,
    )

    # 4. Search
    search_req = {"query": "lazy dog", "top_k": 5}
    search_resp = await client.post(
        "/api/v1/search", json=search_req, headers={"Authorization": f"Bearer {token}"}
    )
    assert search_resp.status_code == 200
    search_data = search_resp.json()

    # Verify results
    assert search_data["total"] > 0
    top_result = search_data["results"][0]
    assert top_result["document_id"] == str(doc_id)
    assert "lazy dog" in top_result["content"].lower()
