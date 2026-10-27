"""Ingestion job service: claim, process, complete, fail.

All job state transitions use the ``version`` column for
optimistic locking. This prevents two workers from operating
on the same job simultaneously.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.logging import get_logger
from src.documents.models import Document
from src.ingestion.models import Chunk, IngestionJob
from src.ingestion.pipeline import ChunkData

logger = get_logger(__name__)


async def claim_next_job(
    db: AsyncSession,
    worker_id: str,
) -> IngestionJob | None:
    """Claim the oldest queued job using SELECT ... FOR UPDATE SKIP LOCKED.

    Also reclaims stale jobs (claimed but not progressed for 10 min).

    Returns:
        The claimed IngestionJob, or None if the queue is empty.
    """
    # First, reset stale claims
    stale_cutoff = datetime.now(UTC) - timedelta(
        minutes=get_settings().worker_stale_claim_timeout_minutes
    )
    await db.execute(
        update(IngestionJob)
        .where(
            IngestionJob.status == "claimed",
            IngestionJob.claimed_at < stale_cutoff,
        )
        .values(status="queued", worker_id=None, claimed_at=None)
    )

    # Claim the next available job
    result = await db.execute(
        text(
            """
            UPDATE ingestion_jobs
            SET status = 'claimed',
                worker_id = :worker_id,
                claimed_at = now(),
                attempt_count = attempt_count + 1,
                version = version + 1
            WHERE id = (
                SELECT id FROM ingestion_jobs
                WHERE status = 'queued'
                  AND attempt_count < max_attempts
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, document_id, user_id, status,
                      attempt_count, max_attempts, version
            """
        ),
        {"worker_id": worker_id},
    )
    row = result.mappings().first()

    if row is None:
        return None

    # Load the full ORM object
    job = await db.get(IngestionJob, row["id"])
    logger.info(
        "job_claimed",
        job_id=str(row["id"]),
        worker_id=worker_id,
        attempt=row["attempt_count"],
    )
    return job


async def mark_running(
    job_id: uuid.UUID,
    version: int,
    db: AsyncSession,
) -> bool:
    """Transition a job from 'claimed' to 'running'.

    Uses optimistic locking via the version column.

    Returns:
        True if the transition succeeded.
    """
    result = await db.execute(
        update(IngestionJob)
        .where(
            IngestionJob.id == job_id,
            IngestionJob.version == version,
        )
        .values(
            status="running",
            started_at=datetime.now(UTC),
            version=version + 1,
        )
    )
    return result.rowcount > 0  # type: ignore[union-attr]


async def complete_job(
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    chunks: list[ChunkData],
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Insert chunks and mark the job as completed.

    This runs in a single transaction so either all chunks are
    inserted and the job is completed, or nothing is committed.
    """
    # Insert chunks
    for chunk in chunks:
        db.add(
            Chunk(
                document_id=document_id,
                user_id=user_id,
                tenant_id=tenant_id,
                content=chunk.content,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                embedding=chunk.embedding,
            )
        )

    # Update document status
    await db.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(status="ready", chunk_count=len(chunks))
    )

    # Update job status
    await db.execute(
        update(IngestionJob)
        .where(IngestionJob.id == job_id)
        .values(
            status="completed",
            completed_at=datetime.now(UTC),
        )
    )

    await db.flush()
    logger.info(
        "job_completed",
        job_id=str(job_id),
        document_id=str(document_id),
        chunk_count=len(chunks),
    )


async def fail_job(
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    error_message: str,
    attempt_count: int,
    max_attempts: int,
    db: AsyncSession,
) -> None:
    """Mark a job as failed (or dead if max attempts reached).

    - ``failed``: can be retried (attempt_count < max_attempts)
    - ``dead``: no more retries
    """
    final_status = "dead" if attempt_count >= max_attempts else "failed"

    # Reset to queued if retryable, otherwise mark as dead
    if final_status == "dead":
        await db.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id)
            .values(
                status="dead",
                error_message=error_message,
            )
        )
        await db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(status="failed", error_message=error_message)
        )
    else:
        # Reset to queued for retry
        await db.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id)
            .values(
                status="queued",
                error_message=error_message,
                worker_id=None,
                claimed_at=None,
            )
        )

    await db.flush()
    logger.warning(
        "job_failed",
        job_id=str(job_id),
        status=final_status,
        attempt=attempt_count,
        max_attempts=max_attempts,
        error=error_message,
    )


async def get_job(
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> IngestionJob | None:
    """Get a job by ID, scoped to the user."""
    result = await db.execute(
        select(IngestionJob).where(
            IngestionJob.id == job_id,
            IngestionJob.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def list_jobs_for_document(
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> list[IngestionJob]:
    """List all ingestion jobs for a document."""
    result = await db.execute(
        select(IngestionJob)
        .where(
            IngestionJob.document_id == document_id,
            IngestionJob.tenant_id == tenant_id,
        )
        .order_by(IngestionJob.created_at.desc())
    )
    return list(result.scalars().all())


async def list_jobs(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    cursor: str | None = None,
    limit: int = 20,
) -> tuple[list[IngestionJob], str | None]:
    """List all ingestion jobs for a tenant with cursor pagination.

    Returns:
        Tuple of (jobs, next_cursor).
    """
    from src.core.pagination import decode_cursor, encode_cursor

    query = (
        select(IngestionJob)
        .where(IngestionJob.tenant_id == tenant_id)
        .order_by(IngestionJob.created_at.desc())
        .limit(limit + 1)
    )

    if cursor:
        cursor_data = decode_cursor(cursor)
        query = query.where(IngestionJob.created_at < cursor_data["created_at"])

    result = await db.execute(query)
    jobs = list(result.scalars().all())

    next_cursor = None
    if len(jobs) > limit:
        jobs = jobs[:limit]
        last = jobs[-1]
        next_cursor = encode_cursor({"created_at": last.created_at.isoformat()})

    return jobs, next_cursor
