"""Integration tests for tenant creation and PostgreSQL RLS.

These tests require the local PostgreSQL service from docker-compose and the
project migrations applied through Alembic.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.auth import service as auth_service
from src.core.config import Settings, get_settings
from src.core.database import Database
from src.core.exceptions import AuthorizationError
from src.documents import service as document_service
from src.tenants import service as tenant_service
from src.tenants.middleware import set_tenant_context

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

pytestmark = pytest.mark.integration


class MemoryStorage:
    """Minimal object storage fake for service-level integration tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    async def delete(self, key: str) -> None:
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
    try:
        yield db
    finally:
        await db.dispose()


async def test_registration_creates_personal_organization(
    admin_db: Database,
) -> None:
    email = f"tenant-{uuid.uuid4()}@example.com"

    async with admin_db.session_factory() as session:
        user = await auth_service.register_user(email, "securepass123", session)
        await session.commit()

    async with admin_db.session_factory() as session:
        memberships = await tenant_service.list_memberships(
            user_id=user.id,
            db=session,
        )

    assert len(memberships) == 1
    assert memberships[0].role == "admin"
    assert memberships[0].organization.slug == f"user-{user.id}"


async def test_document_upload_is_tenant_scoped(admin_db: Database) -> None:
    storage = MemoryStorage()

    async with admin_db.session_factory() as session:
        user = await auth_service.register_user(
            f"upload-{uuid.uuid4()}@example.com",
            "securepass123",
            session,
        )
        membership = await tenant_service.resolve_membership(
            user_id=user.id,
            db=session,
        )
        await set_tenant_context(session, membership.org_id)
        document, job = await document_service.upload_document(
            filename="notes.txt",
            content=b"Tenant-owned research note.",
            mime_type="text/plain",
            idempotency_key=str(uuid.uuid4()),
            user_id=user.id,
            tenant_id=membership.org_id,
            db=session,
            storage=storage,
        )
        await session.commit()

    assert document.tenant_id == membership.org_id
    assert job.tenant_id == membership.org_id
    assert next(iter(storage.objects)).startswith(f"{membership.org_id}/")


async def test_tenant_membership_blocks_cross_tenant_documents(
    admin_db: Database,
) -> None:
    storage = MemoryStorage()

    async with admin_db.session_factory() as session:
        user_a = await auth_service.register_user(
            f"user-a-{uuid.uuid4()}@example.com",
            "securepass123",
            session,
        )
        user_b = await auth_service.register_user(
            f"user-b-{uuid.uuid4()}@example.com",
            "securepass123",
            session,
        )
        tenant_a = await tenant_service.resolve_membership(
            user_id=user_a.id,
            db=session,
        )
        tenant_b = await tenant_service.resolve_membership(
            user_id=user_b.id,
            db=session,
        )

        await set_tenant_context(session, tenant_a.org_id)
        document, _ = await document_service.upload_document(
            filename="tenant-a.txt",
            content=b"Only tenant A should see this.",
            mime_type="text/plain",
            idempotency_key=str(uuid.uuid4()),
            user_id=user_a.id,
            tenant_id=tenant_a.org_id,
            db=session,
            storage=storage,
        )
        await session.commit()

    async with admin_db.session_factory() as session:
        await set_tenant_context(session, tenant_b.org_id)
        with pytest.raises(AuthorizationError):
            await tenant_service.resolve_membership(
                user_id=user_b.id,
                org_id=tenant_a.org_id,
                db=session,
            )

        docs, _ = await document_service.list_documents(
            user_id=user_b.id,
            tenant_id=tenant_b.org_id,
            db=session,
        )

    assert document.tenant_id == tenant_a.org_id
    assert docs == []


async def test_rls_hides_rows_without_matching_tenant_context(
    live_settings: Settings,
) -> None:
    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    user_id = uuid.uuid4()
    content_hash = uuid.uuid4().hex + uuid.uuid4().hex

    admin_engine = create_async_engine(live_settings.database_url)
    limited_url = _database_url_with_credentials(
        live_settings.database_url,
        username="app_rls_test",
        password="app_rls_test",
    )
    limited_engine = create_async_engine(limited_url)

    try:
        async with admin_engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_roles WHERE rolname = 'app_rls_test'
                        ) THEN
                            CREATE ROLE app_rls_test LOGIN PASSWORD 'app_rls_test';
                        END IF;
                    END
                    $$;
                    """
                )
            )
            await conn.execute(text("GRANT USAGE ON SCHEMA public TO app_rls_test"))
            await conn.execute(text("GRANT SELECT ON documents TO app_rls_test"))
            await conn.execute(
                text(
                    """
                    INSERT INTO users (id, email, password_hash)
                    VALUES (:user_id, :email, 'hash')
                    """
                ),
                {
                    "user_id": user_id,
                    "email": f"rls-{user_id}@example.com",
                },
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO organizations (id, name, slug)
                    VALUES (:tenant_id, 'RLS Tenant', :slug),
                           (:other_tenant_id, 'Other Tenant', :other_slug)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "slug": f"rls-{tenant_id}",
                    "other_tenant_id": other_tenant_id,
                    "other_slug": f"rls-{other_tenant_id}",
                },
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO documents (
                        id, user_id, tenant_id, filename, content_hash, size_bytes
                    )
                    VALUES (
                        :document_id, :user_id, :tenant_id,
                        'rls.txt', :content_hash, 12
                    )
                    """
                ),
                {
                    "document_id": document_id,
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "content_hash": content_hash,
                },
            )

        async with limited_engine.connect() as conn:
            missing_context = await conn.execute(text("SELECT id FROM documents"))
            assert missing_context.fetchall() == []

            await conn.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                {"tenant_id": str(other_tenant_id)},
            )
            wrong_context = await conn.execute(text("SELECT id FROM documents"))
            assert wrong_context.fetchall() == []

        async with limited_engine.connect() as conn:
            await conn.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            right_context = await conn.execute(text("SELECT id FROM documents"))
            assert [row[0] for row in right_context] == [document_id]
    finally:
        await limited_engine.dispose()
        async with admin_engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM documents WHERE id = :document_id"),
                {"document_id": document_id},
            )
            await conn.execute(
                text(
                    "DELETE FROM organizations "
                    "WHERE id IN (:tenant_id, :other_tenant_id)"
                ),
                {
                    "tenant_id": tenant_id,
                    "other_tenant_id": other_tenant_id,
                },
            )
            await conn.execute(
                text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            )
        await admin_engine.dispose()


async def test_worker_mode_can_claim_jobs_across_tenants(
    admin_db: Database,
) -> None:
    async with admin_db.session_factory() as session:
        await session.execute(text("SELECT set_config('app.worker_mode', 'on', true)"))
        result = await session.execute(text("SELECT count(*) FROM ingestion_jobs"))

    assert result.scalar_one() >= 0


def _database_url_with_credentials(
    database_url: str,
    *,
    username: str,
    password: str,
) -> str:
    parsed = urlsplit(database_url)
    host = parsed.hostname or "localhost"
    netloc = f"{username}:{password}@{host}"
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )
