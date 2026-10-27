"""Concurrency tests for SKIP LOCKED queue worker pattern."""

import asyncio
import uuid

import pytest

from src.documents.models import Document
from src.ingestion.models import IngestionJob
from src.ingestion.service import claim_next_job
from tests.factories import create_test_user, get_user_workspace

pytestmark = [pytest.mark.asyncio, pytest.mark.concurrency]


async def test_skip_locked_prevents_double_claim() -> None:
    """Test that concurrent workers claim different jobs due to SKIP LOCKED."""

    from src.core.config import get_settings

    settings = get_settings()
    from src.core.database import Database

    admin_db = Database(settings)
    from sqlalchemy.ext.asyncio import create_async_engine

    # 1. Setup tenant and create two pending jobs
    async with admin_db.session_factory() as session:
        from sqlalchemy import text

        await session.execute(text("DELETE FROM ingestion_jobs"))
        await session.execute(text("DELETE FROM documents"))
        await session.commit()

        user = await create_test_user(session, email="queue@example.com")
        tenant = await get_user_workspace(user, session)

        doc1 = Document(
            id=uuid.uuid4(),
            user_id=user.id,
            tenant_id=tenant.id,
            filename="doc1.txt",
            content_hash="hash1",
            size_bytes=100,
            status="pending",
        )
        doc2 = Document(
            id=uuid.uuid4(),
            user_id=user.id,
            tenant_id=tenant.id,
            filename="doc2.txt",
            content_hash="hash2",
            size_bytes=100,
            status="pending",
        )
        session.add_all([doc1, doc2])

        job1 = IngestionJob(
            document_id=doc1.id,
            user_id=user.id,
            tenant_id=tenant.id,
            idempotency_key="job1",
        )
        job2 = IngestionJob(
            document_id=doc2.id,
            user_id=user.id,
            tenant_id=tenant.id,
            idempotency_key="job2",
        )
        session.add_all([job1, job2])
        await session.commit()

    # We need to simulate concurrent claims. Because db_session shares
    # a single transaction/connection in tests, SKIP LOCKED inside the same
    # transaction doesn't block itself. However, testing SKIP LOCKED properly
    # requires independent connections.

    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn1, engine.connect() as conn2:
        async with conn1.begin(), conn2.begin():
            # Worker 1 runs the claim query but we don't commit yet
            # claim_next_job does UPDATE ... RETURNING which locks the row
            # We can run them concurrently and they should get different jobs

            # Since claim_next_job takes a session, we'll wrap the connections
            from sqlalchemy.ext.asyncio import AsyncSession as Session

            session1 = Session(bind=conn1)
            session2 = Session(bind=conn2)

            # Gather both claims simultaneously
            claimed_job1, claimed_job2 = await asyncio.gather(
                claim_next_job(worker_id="worker1", db=session1),
                claim_next_job(worker_id="worker2", db=session2),
            )

            assert claimed_job1 is not None
            assert claimed_job2 is not None

            # Must claim different jobs
            assert claimed_job1.id != claimed_job2.id

            # Cleanup
            await session1.close()
            await session2.close()

    await engine.dispose()
