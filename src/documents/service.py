"""Document business logic: upload, list, get, delete."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictError, NotFoundError
from src.core.logging import get_logger
from src.core.pagination import decode_cursor, encode_cursor
from src.documents.models import Document
from src.documents.storage import ObjectStorage
from src.ingestion.models import IngestionJob

logger = get_logger(__name__)


async def upload_document(
    *,
    filename: str,
    content: bytes,
    mime_type: str | None,
    idempotency_key: str,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    storage: ObjectStorage,
) -> tuple[Document, IngestionJob]:
    """Upload a document, store in MinIO, and queue an ingestion job.

    Deduplication:
      1. Idempotency key: same key for this user returns existing doc.
      2. Content hash: same file content for this user returns existing doc.

    Returns:
        Tuple of (Document, IngestionJob).

    Raises:
        ConflictError: If a different document exists with the same
            idempotency key (unlikely but guards against misuse).
    """
    content_hash = hashlib.sha256(content).hexdigest()

    # ── Check idempotency ────────────────────────────────────
    existing_job = await db.execute(
        select(IngestionJob).where(
            IngestionJob.tenant_id == tenant_id,
            IngestionJob.idempotency_key == idempotency_key,
        )
    )
    job = existing_job.scalar_one_or_none()
    if job is not None:
        doc = await db.get(Document, job.document_id)
        if doc is not None:
            logger.info(
                "idempotent_upload_hit",
                document_id=str(doc.id),
                idempotency_key=idempotency_key,
            )
            return doc, job

    # ── Check content dedup ──────────────────────────────────
    existing_doc = await db.execute(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.content_hash == content_hash,
            Document.deleted_at.is_(None),
        )
    )
    doc = existing_doc.scalar_one_or_none()
    if doc is not None:
        # Find or create job for existing doc
        existing_job_for_doc = await db.execute(
            select(IngestionJob)
            .where(
                IngestionJob.document_id == doc.id,
                IngestionJob.tenant_id == tenant_id,
            )
            .order_by(IngestionJob.created_at.desc())
        )
        job = existing_job_for_doc.scalars().first()
        if job is not None:
            logger.info(
                "content_dedup_hit",
                document_id=str(doc.id),
                content_hash=content_hash,
            )
            return doc, job

    # ── Upload to MinIO ──────────────────────────────────────
    doc_id = uuid.uuid4()
    storage_key = f"{tenant_id}/{doc_id}/{filename}"
    await storage.upload(storage_key, content, mime_type or "application/octet-stream")

    # ── Create Document + Job atomically ─────────────────────
    document = Document(
        id=doc_id,
        user_id=user_id,
        tenant_id=tenant_id,
        filename=filename,
        content_hash=content_hash,
        size_bytes=len(content),
        mime_type=mime_type,
        storage_key=storage_key,
        status="pending",
    )

    ingestion_job = IngestionJob(
        document_id=doc_id,
        user_id=user_id,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
    )
    try:
        async with db.begin_nested():
            db.add(document)
            db.add(ingestion_job)
            await db.flush()
    except IntegrityError as exc:
        try:
            await storage.delete(storage_key)
        except Exception:
            logger.warning(
                "orphan_upload_cleanup_failed",
                document_id=str(doc_id),
                storage_key=storage_key,
            )

        existing = await _find_existing_upload(
            content_hash=content_hash,
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
            db=db,
        )
        if existing is None:
            raise ConflictError(
                "Upload conflicted with another request. Retry the upload."
            ) from exc
        return existing

    logger.info(
        "document_uploaded",
        document_id=str(doc_id),
        job_id=str(ingestion_job.id),
        filename=filename,
        size_bytes=len(content),
    )
    return document, ingestion_job


async def _find_existing_upload(
    *,
    content_hash: str,
    idempotency_key: str,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> tuple[Document, IngestionJob] | None:
    """Find the winner of a concurrent idempotency/content-hash insert."""
    existing_job = await db.execute(
        select(IngestionJob).where(
            IngestionJob.tenant_id == tenant_id,
            IngestionJob.idempotency_key == idempotency_key,
        )
    )
    job = existing_job.scalar_one_or_none()
    if job is not None:
        doc = await db.get(Document, job.document_id)
        if doc is not None:
            return doc, job

    existing_doc = await db.execute(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.content_hash == content_hash,
            Document.deleted_at.is_(None),
        )
    )
    doc = existing_doc.scalar_one_or_none()
    if doc is None:
        return None

    existing_job_for_doc = await db.execute(
        select(IngestionJob)
        .where(
            IngestionJob.document_id == doc.id,
            IngestionJob.tenant_id == tenant_id,
        )
        .order_by(IngestionJob.created_at.desc())
    )
    job = existing_job_for_doc.scalars().first()
    if job is None:
        return None
    return doc, job


async def list_documents(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    cursor: str | None = None,
    limit: int = 20,
) -> tuple[list[Document], str | None]:
    """List non-deleted documents for a user with cursor pagination.

    Returns:
        Tuple of (documents, next_cursor).
    """
    query = (
        select(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
        )
        .order_by(Document.created_at.desc())
        .limit(limit + 1)
    )

    if cursor:
        cursor_data = decode_cursor(cursor)
        query = query.where(Document.created_at < cursor_data["created_at"])

    result = await db.execute(query)
    docs = list(result.scalars().all())

    next_cursor = None
    if len(docs) > limit:
        docs = docs[:limit]
        last = docs[-1]
        next_cursor = encode_cursor({"created_at": last.created_at.isoformat()})

    return docs, next_cursor


async def get_document(
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> Document:
    """Get a single document by ID.

    Raises:
        NotFoundError: If the document does not exist or is deleted.
    """
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise NotFoundError("Document", str(document_id))
    return doc


async def soft_delete_document(
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    storage: ObjectStorage,
) -> None:
    """Soft-delete a document and remove its file from MinIO.

    Raises:
        NotFoundError: If the document does not exist.
    """
    doc = await get_document(document_id, user_id, tenant_id, db)

    # Soft-delete in database
    from datetime import datetime

    await db.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(
            deleted_at=datetime.now(UTC),
            status="failed",
        )
    )

    # Remove from MinIO (best-effort)
    if doc.storage_key:
        try:
            await storage.delete(doc.storage_key)
        except Exception:
            logger.warning(
                "minio_delete_failed",
                document_id=str(document_id),
                storage_key=doc.storage_key,
            )

    await db.flush()
    logger.info("document_deleted", document_id=str(document_id))


async def list_chunks(
    document_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    cursor: str | None = None,
    limit: int = 20,
) -> tuple[list, str | None]:
    """List chunks for a document with cursor pagination.

    Returns:
        Tuple of (chunks, next_cursor).
    """
    from src.ingestion.models import Chunk

    query = (
        select(Chunk)
        .where(
            Chunk.document_id == document_id,
            Chunk.tenant_id == tenant_id,
        )
        .order_by(Chunk.chunk_index.asc())
        .limit(limit + 1)
    )

    if cursor:
        cursor_data = decode_cursor(cursor)
        query = query.where(Chunk.chunk_index > int(cursor_data["chunk_index"]))

    result = await db.execute(query)
    chunks = list(result.scalars().all())

    next_cursor = None
    if len(chunks) > limit:
        chunks = chunks[:limit]
        last = chunks[-1]
        next_cursor = encode_cursor({"chunk_index": last.chunk_index})

    return chunks, next_cursor
