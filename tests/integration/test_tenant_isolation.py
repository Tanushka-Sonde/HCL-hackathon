"""Integration tests for tenant isolation and RLS."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings
from src.core.security import create_access_token
from tests.factories import create_test_user

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_tenant_isolation_list_documents(
    client: AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    """Test that Tenant A cannot see Tenant B's documents."""

    # 1. Create two users and their workspaces
    user_a = await create_test_user(db_session, email="tenant_a@example.com")
    user_b = await create_test_user(db_session, email="tenant_b@example.com")

    token_a = create_access_token(str(user_a.id), user_a.email, settings)
    token_b = create_access_token(str(user_b.id), user_b.email, settings)

    headers_a = {"Authorization": f"Bearer {token_a}", "Idempotency-Key": "key-a"}
    headers_b = {"Authorization": f"Bearer {token_b}", "Idempotency-Key": "key-b"}

    # 2. Upload doc for Tenant A
    files_a = {"file": ("doc_a.txt", b"Tenant A Content", "text/plain")}
    resp_a = await client.post("/api/v1/documents", files=files_a, headers=headers_a)
    assert resp_a.status_code == 201

    # 3. Upload doc for Tenant B
    files_b = {"file": ("doc_b.txt", b"Tenant B Content", "text/plain")}
    resp_b = await client.post("/api/v1/documents", files=files_b, headers=headers_b)
    assert resp_b.status_code == 201

    # 4. List documents for Tenant A
    resp_list_a = await client.get(
        "/api/v1/documents", headers={"Authorization": f"Bearer {token_a}"}
    )
    assert resp_list_a.status_code == 200
    docs_a = resp_list_a.json()["items"]
    assert len(docs_a) == 1
    assert docs_a[0]["filename"] == "doc_a.txt"

    # 5. List documents for Tenant B
    resp_list_b = await client.get(
        "/api/v1/documents", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert resp_list_b.status_code == 200
    docs_b = resp_list_b.json()["items"]
    assert len(docs_b) == 1
    assert docs_b[0]["filename"] == "doc_b.txt"


async def test_tenant_isolation_get_document(
    client: AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    """Test that Tenant A cannot fetch Tenant B's specific document."""
    user_a = await create_test_user(db_session, email="a2@example.com")
    user_b = await create_test_user(db_session, email="b2@example.com")

    token_a = create_access_token(str(user_a.id), user_a.email, settings)
    token_b = create_access_token(str(user_b.id), user_b.email, settings)

    # Upload doc for Tenant B
    files_b = {"file": ("doc_b2.txt", b"Tenant B2 Content", "text/plain")}
    resp_b = await client.post(
        "/api/v1/documents",
        files=files_b,
        headers={"Authorization": f"Bearer {token_b}", "Idempotency-Key": "key-b2"},
    )
    doc_id_b = resp_b.json()["document"]["id"]

    # Tenant A attempts to get Tenant B's document
    resp_get_a = await client.get(
        f"/api/v1/documents/{doc_id_b}", headers={"Authorization": f"Bearer {token_a}"}
    )
    assert resp_get_a.status_code == 404
