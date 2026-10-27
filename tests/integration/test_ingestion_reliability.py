"""Integration tests for ingestion reliability and health readiness."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text, update

from src.auth import service as auth_service
from src.core.config import Settings, get_settings
from src.core.database import Database
from src.documents import service as document_service
from src.documents.models import Document
from src.ingestion import service as ingestion_service
from src.ingestion.models import IngestionJob
from src.main import create_app
from src.tenants import service as tenant_service
from src.tenants.middleware import set_tenant_context, set_worker_context

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

pytestmark = pytest.mark.integration


class MemoryStorage:
    """Minimal object storage fake for service-level integration tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


@pytest.fixture()
async def live_settings() -> AsyncGenerator[Settings, None]:
    settings = get_settings()
    db = Database(settings)
    try:
        async with db.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL integration database is unavailable: {exc}")
    finally:
        await db.dispose()

    yield settings


@pytest.fixture()
async def admin_db(live_settings: Settings) -> AsyncGenerator[Database, None]:
    db = Database(live_settings)
    async with db.session_factory() as session:
        await session.execute(text("DELETE FROM ingestion_jobs"))
        await session.execute(text("DELETE FROM documents"))
        await session.execute(text("DELETE FROM org_memberships"))
        await session.execute(text("DELETE FROM organizations"))
        await session.execute(text("DELETE FROM api_keys"))
        await session.execute(text("DELETE FROM refresh_tokens"))
        await session.execute(text("DELETE FROM users"))
        await session.commit()
    try:
        yield db
    finally:
        await db.dispose()


async def test_two_workers_do_not_claim_same_job(admin_db: Database) -> None:
    first = await _create_document_and_job(admin_db, queue_order=0)
    second = await _create_document_and_job(admin_db, queue_order=1)

    claimed = await asyncio.gather(
        _claim_one(admin_db, "phase3-worker-a"),
        _claim_one(admin_db, "phase3-worker-b"),
    )

    claimed_ids = {job.id for job in claimed if job is not None}
    assert claimed_ids == {first.job_id, second.job_id}
    assert len(claimed_ids) == 2


async def test_stale_claim_is_requeued_and_reclaimed(admin_db: Database) -> None:
    fixture = await _create_document_and_job(admin_db, queue_order=2)

    async with admin_db.session_factory() as session:
        await set_worker_context(session)
        await session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == fixture.job_id)
            .values(
                status="claimed",
                worker_id="crashed-worker",
                claimed_at=datetime.now(UTC) - timedelta(minutes=20),
            )
        )
        await session.commit()

    reclaimed = await _claim_one(admin_db, "recovery-worker")

    assert reclaimed is not None
    assert reclaimed.id == fixture.job_id
    assert reclaimed.status == "claimed"
    assert reclaimed.worker_id == "recovery-worker"
    assert reclaimed.attempt_count == 1


async def test_mark_running_rejects_stale_version(admin_db: Database) -> None:
    fixture = await _create_document_and_job(admin_db, queue_order=3)
    claimed = await _claim_one(admin_db, "version-worker")

    assert claimed is not None
    assert claimed.id == fixture.job_id

    async with admin_db.session_factory() as session:
        await set_worker_context(session)
        transitioned = await ingestion_service.mark_running(
            claimed.id,
            claimed.version,
            session,
        )
        repeated = await ingestion_service.mark_running(
            claimed.id,
            claimed.version,
            session,
        )
        await session.commit()

    assert transitioned is True
    assert repeated is False


async def test_fail_job_requeues_then_dead_letters(admin_db: Database) -> None:
    fixture = await _create_document_and_job(admin_db, queue_order=4)

    async with admin_db.session_factory() as session:
        await set_worker_context(session)
        await ingestion_service.fail_job(
            job_id=fixture.job_id,
            document_id=fixture.document_id,
            error_message="temporary LLM outage",
            attempt_count=1,
            max_attempts=3,
            db=session,
        )
        await session.commit()

    async with admin_db.session_factory() as session:
        await set_worker_context(session)
        job = await session.get(IngestionJob, fixture.job_id)
        assert job is not None
        assert job.status == "queued"
        assert job.worker_id is None
        assert job.claimed_at is None

        await ingestion_service.fail_job(
            job_id=fixture.job_id,
            document_id=fixture.document_id,
            error_message="persistent LLM outage",
            attempt_count=3,
            max_attempts=3,
            db=session,
        )
        await session.commit()

    async with admin_db.session_factory() as session:
        await set_worker_context(session)
        job = await session.get(IngestionJob, fixture.job_id)
        document = await session.get(Document, fixture.document_id)

    assert job is not None
    assert document is not None
    assert job.status == "dead"
    assert document.status == "failed"
    assert document.error_message == "persistent LLM outage"


async def test_concurrent_duplicate_upload_returns_existing_job(
    admin_db: Database,
) -> None:
    user_id, tenant_id = await _create_user_and_tenant(admin_db)
    storage = MemoryStorage()
    content = f"same duplicate content {uuid.uuid4()}".encode()
    idempotency_key = str(uuid.uuid4())

    async def upload_once() -> tuple[uuid.UUID, uuid.UUID]:
        async with admin_db.session_factory() as session:
            await set_tenant_context(session, tenant_id)
            document, job = await document_service.upload_document(
                filename="duplicate.txt",
                content=content,
                mime_type="text/plain",
                idempotency_key=idempotency_key,
                user_id=user_id,
                tenant_id=tenant_id,
                db=session,
                storage=storage,
            )
            await session.commit()
            return document.id, job.id

    results = await asyncio.gather(upload_once(), upload_once())

    document_ids = {document_id for document_id, _ in results}
    job_ids = {job_id for _, job_id in results}
    assert len(document_ids) == 1
    assert len(job_ids) == 1
    assert len(storage.objects) == 1


async def test_ready_health_reports_database_ok(
    live_settings: Settings,
) -> None:
    app = create_app()
    db = Database(live_settings)
    app.state.db = db
    app.state.settings = live_settings

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            response = await client.get("/health/ready")
    finally:
        await db.dispose()

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["checks"]["database"] == "ok"


async def test_ready_health_returns_503_when_database_fails() -> None:
    app = create_app()
    app.state.db = BrokenDatabase()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["database"].startswith("error:")


class BrokenDatabase:
    def session_factory(self) -> BrokenSession:
        return BrokenSession()


class BrokenSession:
    async def __aenter__(self) -> BrokenSession:
        raise RuntimeError("database unavailable")

    async def __aexit__(self, *_args: object) -> None:
        return None


class UploadFixture:
    def __init__(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.document_id = document_id
        self.job_id = job_id


async def _create_user_and_tenant(
    db: Database,
) -> tuple[uuid.UUID, uuid.UUID]:
    async with db.session_factory() as session:
        user = await auth_service.register_user(
            f"phase3-{uuid.uuid4()}@example.com",
            "securepass123",
            session,
        )
        membership = await tenant_service.resolve_membership(
            user_id=user.id,
            db=session,
        )
        await session.commit()
        return user.id, membership.org_id


async def _create_document_and_job(
    db: Database,
    *,
    queue_order: int,
) -> UploadFixture:
    user_id, tenant_id = await _create_user_and_tenant(db)
    storage = MemoryStorage()

    async with db.session_factory() as session:
        await set_tenant_context(session, tenant_id)
        document, job = await document_service.upload_document(
            filename=f"phase3-{queue_order}.txt",
            content=f"phase3 reliability {uuid.uuid4()}".encode(),
            mime_type="text/plain",
            idempotency_key=str(uuid.uuid4()),
            user_id=user_id,
            tenant_id=tenant_id,
            db=session,
            storage=storage,
        )
        await session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job.id)
            .values(created_at=datetime(1970, 1, queue_order + 1, tzinfo=UTC))
        )
        await session.commit()
        return UploadFixture(
            user_id=user_id,
            tenant_id=tenant_id,
            document_id=document.id,
            job_id=job.id,
        )


async def _claim_one(db: Database, worker_id: str) -> IngestionJob | None:
    async with db.session_factory() as session:
        await set_worker_context(session)
        job = await ingestion_service.claim_next_job(session, worker_id)
        await session.commit()
        return job
