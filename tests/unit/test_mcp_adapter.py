"""Unit tests for MCP adapter serialization helpers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from mcp_server.adapters.research_platform import (
    _document_to_dict,
    _job_to_dict,
    _parse_uuid,
)


@dataclass
class FakeDocument:
    id: uuid.UUID
    tenant_id: uuid.UUID
    filename: str
    status: str
    size_bytes: int
    mime_type: str | None
    chunk_count: int
    content_hash: str
    created_at: datetime
    updated_at: datetime


@dataclass
class FakeJob:
    id: uuid.UUID
    document_id: uuid.UUID
    tenant_id: uuid.UUID
    status: str
    attempt_count: int
    max_attempts: int
    error_message: str | None
    claimed_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


def test_parse_uuid_accepts_valid_uuid() -> None:
    value = uuid.uuid4()
    assert _parse_uuid(str(value), "user_id") == value


def test_document_to_dict_is_json_ready() -> None:
    now = datetime.now(UTC)
    document = FakeDocument(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        filename="paper.txt",
        status="ready",
        size_bytes=123,
        mime_type="text/plain",
        chunk_count=2,
        content_hash="a" * 64,
        created_at=now,
        updated_at=now,
    )

    result = _document_to_dict(document)

    assert result["id"] == str(document.id)
    assert result["tenant_id"] == str(document.tenant_id)
    assert result["created_at"] == now.isoformat()
    assert result["filename"] == "paper.txt"


def test_job_to_dict_is_json_ready() -> None:
    now = datetime.now(UTC)
    job = FakeJob(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        status="queued",
        attempt_count=0,
        max_attempts=3,
        error_message=None,
        claimed_at=None,
        started_at=None,
        completed_at=None,
        created_at=now,
    )

    result = _job_to_dict(job)

    assert result["id"] == str(job.id)
    assert result["document_id"] == str(job.document_id)
    assert result["tenant_id"] == str(job.tenant_id)
    assert result["created_at"] == now.isoformat()
