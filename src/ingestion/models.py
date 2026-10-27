"""Ingestion database models: Chunk and IngestionJob."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base

if TYPE_CHECKING:
    from src.documents.models import Document

# Embedding dimension for all-MiniLM-L6-v2
EMBEDDING_DIM: int = 384


class Chunk(Base):
    """A semantic chunk of a document with dense and sparse representations.

    Dense: ``embedding`` column indexed with HNSW (pgvector).
    Sparse: ``tsv`` column indexed with GIN (PostgreSQL tsvector).
    Both are used for hybrid retrieval with Reciprocal Rank Fusion.
    """

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    content: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
    )
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    # ── Relationships ────────────────────────────────────────
    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_user_id", "user_id"),
        Index("ix_chunks_tenant_id", "tenant_id"),
        # HNSW and GIN indexes are created via raw SQL in the migration
        # because SQLAlchemy Index() does not support USING hnsw/gin syntax.
    )

    def __repr__(self) -> str:
        return f"<Chunk id={self.id} doc={self.document_id} idx={self.chunk_index}>"


class IngestionJob(Base):
    """Background ingestion job, queued and claimed via SKIP LOCKED.

    Lifecycle: queued → claimed → running → completed | failed | dead.

    Workers claim jobs with::

        UPDATE ingestion_jobs
        SET status = 'claimed', worker_id = :wid, claimed_at = now(),
            version = version + 1
        WHERE id = (
            SELECT id FROM ingestion_jobs
            WHERE status = 'queued' AND attempt_count < max_attempts
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING *;

    The ``version`` column provides optimistic locking for status updates.
    """

    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    status: Mapped[str] = mapped_column(
        String(20), default="queued", server_default=text("'queued'")
    )
    idempotency_key: Mapped[str] = mapped_column(String(255))
    worker_id: Mapped[str | None] = mapped_column(String(100))
    attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, default=3, server_default=text("3")
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    error_message: Mapped[str | None] = mapped_column(Text)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    # ── Relationships ────────────────────────────────────────
    document: Mapped[Document] = relationship(back_populates="ingestion_jobs")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_jobs_tenant_idempotency"
        ),
        CheckConstraint(
            "status IN ('queued', 'claimed', 'running', 'completed', 'failed', 'dead')",
            name="ck_jobs_status_valid",
        ),
        Index(
            "ix_jobs_dequeue",
            "created_at",
            postgresql_where=text("status = 'queued'"),
        ),
        Index("ix_jobs_document_id", "document_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<IngestionJob id={self.id} status={self.status} "
            f"attempt={self.attempt_count}/{self.max_attempts}>"
        )
