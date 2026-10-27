"""Concurrency tests for optimistic locking (version column)."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.documents.models import Document
from src.ingestion.models import IngestionJob
from src.ingestion.service import mark_running
from tests.factories import create_test_user, get_user_workspace

pytestmark = [pytest.mark.asyncio, pytest.mark.concurrency]


async def test_optimistic_lock_prevents_lost_update(db_session: AsyncSession) -> None:
    """Test that updating a job with a stale version raises ConflictError."""

    # 1. Setup
    user = await create_test_user(db_session, email="opt_lock@example.com")
    tenant = await get_user_workspace(user, db_session)

    doc = Document(
        id=uuid.uuid4(),
        user_id=user.id,
        tenant_id=tenant.id,
        filename="opt.txt",
        content_hash="opt-hash",
        size_bytes=10,
        status="pending",
    )
    db_session.add(doc)
    await db_session.flush()

    job = IngestionJob(
        document_id=doc.id,
        user_id=user.id,
        tenant_id=tenant.id,
        idempotency_key="opt-job",
        status="claimed",
        worker_id="worker-1",
        version=1,
    )
    db_session.add(job)
    await db_session.flush()

    # 2. Worker 1 reads the job (version 1)
    worker1_job = IngestionJob(id=job.id, version=job.version)

    # 3. Worker 2 reads the same job concurrently and updates it
    await mark_running(job.id, version=job.version, db=db_session)

    # 4. Worker 1 attempts to update it using its stale version (1)
    result = await mark_running(
        worker1_job.id, version=worker1_job.version, db=db_session
    )
    assert result is False
