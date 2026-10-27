"""Integration tests for document upload and deduplication."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings
from src.core.security import create_access_token
from tests.factories import create_test_user

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_duplicate_upload_idempotency_key(
    client: AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    """Test that uploading with the same idempotency key returns the same document."""
    user = await create_test_user(db_session)
    token = create_access_token(str(user.id), user.email, settings)
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "test-idem-key-1"}

    # First upload
    files = {"file": ("test.txt", b"Hello world", "text/plain")}
    resp1 = await client.post("/api/v1/documents", files=files, headers=headers)
    assert resp1.status_code == 201
    doc1 = resp1.json()["document"]

    # Second upload with same key, different content
    files2 = {"file": ("test2.txt", b"Different content", "text/plain")}
    resp2 = await client.post("/api/v1/documents", files=files2, headers=headers)
    assert resp2.status_code == 201
    doc2 = resp2.json()["document"]

    # Should return the exact same document ID due to idempotency key
    assert doc1["id"] == doc2["id"]


async def test_duplicate_upload_content_hash(
    client: AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    """Test that uploading identical content with a different key dedups by hash."""
    user = await create_test_user(db_session, email="dedup@example.com")
    token = create_access_token(str(user.id), user.email, settings)

    content = b"Content dedup test"

    # First upload
    files1 = {"file": ("first.txt", content, "text/plain")}
    headers1 = {"Authorization": f"Bearer {token}", "Idempotency-Key": "key-1"}
    resp1 = await client.post("/api/v1/documents", files=files1, headers=headers1)
    assert resp1.status_code == 201
    doc1 = resp1.json()["document"]

    # Second upload, different key, same content
    files2 = {"file": ("second.txt", content, "text/plain")}
    headers2 = {"Authorization": f"Bearer {token}", "Idempotency-Key": "key-2"}
    resp2 = await client.post("/api/v1/documents", files=files2, headers=headers2)
    assert resp2.status_code == 201
    doc2 = resp2.json()["document"]

    # Should return the exact same document ID due to content hash
    assert doc1["id"] == doc2["id"]
